import os
import json
import pandas as pd
import sqlite3
import dash
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx

from dash import dcc, html, Input, Output, State, callback, dash_table
from flask_caching import Cache

# Initialize the Dash app with Bootstrap theme
app = dash.Dash(__name__,
                external_stylesheets=[dbc.themes.DARKLY],
                meta_tags=[{'name': 'viewport', 'content': 'width=device-width, initial-scale=1'}])

# Setup cache
cache = Cache(app.server, config={
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': 'cache-directory',
    'CACHE_DEFAULT_TIMEOUT': 300  # 5 minutes
})


# Setup SQLite database for pattern annotations
def setup_database():
    conn = sqlite3.connect('pattern_annotations.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pattern_annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        pattern_type TEXT NOT NULL,
        pattern_time TEXT NOT NULL,
        explanation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

@cache.memoize(timeout=60)  # Cache for 1 minute
def get_filtered_pattern_data(pattern_data, pattern_type, selected_tickers):
    """Get pattern data filtered by ticker with caching."""
    if not pattern_data or pattern_type not in pattern_data:
        return {}

    pattern_subset = pattern_data[pattern_type]

    if not selected_tickers:
        return pattern_subset

    return {ticker: data for ticker, data in pattern_subset.items()
            if ticker in selected_tickers}


@cache.memoize(timeout=300)  # Cache for 5 minutes
def get_available_tickers(pattern_data):
    """Get list of available tickers with caching."""
    available_tickers = []
    if pattern_data and 'recurring_patterns' in pattern_data:
        available_tickers = list(pattern_data['recurring_patterns'].keys())
    return available_tickers

# CRUD operations for pattern annotations
def get_pattern_annotation(ticker, pattern_type, pattern_time):
    """Get annotation for a specific pattern with error handling."""
    try:
        conn = sqlite3.connect('pattern_annotations.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT explanation FROM pattern_annotations WHERE ticker = ? AND pattern_type = ? AND pattern_time = ?",
            (ticker, pattern_type, pattern_time)
        )
        result = cursor.fetchone()
        conn.close()

        if result:
            return result[0]
        return ""
    except sqlite3.Error as e:
        print(f"Database error retrieving annotation: {str(e)}")
        return ""
    except Exception as e:
        print(f"Error retrieving annotation: {str(e)}")
        return ""


def save_pattern_annotation(ticker, pattern_type, pattern_time, explanation):
    conn = sqlite3.connect('pattern_annotations.db')
    cursor = conn.cursor()

    # Check if annotation already exists
    cursor.execute(
        "SELECT id FROM pattern_annotations WHERE ticker = ? AND pattern_type = ? AND pattern_time = ?",
        (ticker, pattern_type, pattern_time)
    )
    existing = cursor.fetchone()

    if existing:
        # Update existing annotation
        cursor.execute(
            "UPDATE pattern_annotations SET explanation = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (explanation, existing[0])
        )
    else:
        # Create new annotation
        cursor.execute(
            "INSERT INTO pattern_annotations (ticker, pattern_type, pattern_time, explanation) VALUES (?, ?, ?, ?)",
            (ticker, pattern_type, pattern_time, explanation)
        )

    conn.commit()
    conn.close()
    return True


def delete_pattern_annotation(ticker, pattern_type, pattern_time):
    conn = sqlite3.connect('pattern_annotations.db')
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM pattern_annotations WHERE ticker = ? AND pattern_type = ? AND pattern_time = ?",
        (ticker, pattern_type, pattern_time)
    )
    conn.commit()
    conn.close()
    return True


def get_all_annotations():
    conn = sqlite3.connect('pattern_annotations.db')
    df = pd.read_sql_query("SELECT * FROM pattern_annotations", conn)
    conn.close()
    return df

# Define pattern file types to load
pattern_files = [
    'recurring_patterns',
    'temporal_clusters',
    'trend_reversals',
    'time_correlations',
    'time_shifts',
    'pattern_summary'
]

# Load pattern data
def load_pattern_data(file_path='pattern_analysis_results'):
    """
    Load pattern data from JSON files with robust error handling.
    
    Parameters:
    file_path (str): Path to directory containing pattern JSON files
    
    Returns:
    dict: Dictionary of loaded pattern data
    """
    pattern_data = {}

    # Create directory if it doesn't exist
    if not os.path.exists(file_path):
        try:
            os.makedirs(file_path)
            print(f"Created directory: {file_path}")
        except Exception as e:
            print(f"Error creating directory {file_path}: {str(e)}")

    for pattern_type in pattern_files:
        file_name = os.path.join(file_path, f"{pattern_type}.json")
        try:
            if os.path.exists(file_name):
                with open(file_name, 'r') as f:
                    pattern_data[pattern_type] = json.load(f)
            else:
                print(f"Warning: Pattern file {file_name} not found. Using empty data.")
                pattern_data[pattern_type] = {}
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON in {file_name}. Using empty data.")
            pattern_data[pattern_type] = {}
        except Exception as e:
            print(f"Error loading {file_name}: {str(e)}. Using empty data.")
            pattern_data[pattern_type] = {}

    return pattern_data


# Utility to convert time string to minutes since midnight
def time_to_minutes(time_str):
    """Convert time string to minutes since midnight."""
    try:
        hours, minutes = map(int, time_str.split(':'))
        return hours * 60 + minutes
    except:
        return 0


# Utility to convert minutes to time string
def minutes_to_time(minutes):
    """Convert minutes since midnight to time string."""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


# Create a heatmap of pattern occurrences by hour and ticker
def create_pattern_heatmap(pattern_data, selected_tickers=None):
    """Create heatmap of pattern occurrences with input validation."""
    # Validate inputs
    if not isinstance(pattern_data, dict):
        print("Warning: pattern_data is not a dictionary")
        return go.Figure().update_layout(title="Invalid pattern data format")

    if 'recurring_patterns' not in pattern_data:
        return go.Figure().update_layout(title="No pattern data available")

    recurring_patterns = pattern_data['recurring_patterns']
    if not recurring_patterns:
        return go.Figure().update_layout(title="No recurring patterns available")

    if not pattern_data or 'recurring_patterns' not in pattern_data:
        return go.Figure().update_layout(title="No pattern data available")

    recurring_patterns = pattern_data['recurring_patterns']  # Use parameter, not global
    if not recurring_patterns:
        return go.Figure().update_layout(title="No recurring patterns available")

    # Filter by selected tickers if provided
    if selected_tickers:
        recurring_patterns = {ticker: data for ticker, data in recurring_patterns.items()
                              if ticker in selected_tickers}

    if not recurring_patterns:
        return go.Figure().update_layout(title="No patterns for selected tickers")

    # Create dataframe for heatmap
    rows = []
    for ticker, ticker_patterns in recurring_patterns.items():
        for time_str, pattern in ticker_patterns.items():
            hour = int(time_str.split(':')[0])
            rows.append({
                'Ticker': ticker,
                'Hour': hour,
                'Count': 1,
                'Mean Price Change': pattern.get('mean_price_change', 0),
                'Direction': pattern.get('consistent_direction', 'neutral')
            })

    df = pd.DataFrame(rows)

    # Aggregate by ticker and hour
    if not df.empty:
        heatmap_data = df.groupby(['Ticker', 'Hour']).agg({
            'Count': 'sum',
            'Mean Price Change': 'mean'
        }).reset_index()

        # Pivot for heatmap format
        pivot_df = heatmap_data.pivot(index='Ticker', columns='Hour', values='Count').fillna(0)

        # Create heatmap
        fig = px.imshow(
            pivot_df,
            labels=dict(x="Hour of Day", y="Ticker", color="Pattern Count"),
            x=list(range(24)),
            color_continuous_scale='YlOrRd',
            aspect="auto"
        )

        # Add trading session overlay if available
        if 'pattern_summary' in patterns and 'session_times' in patterns['pattern_summary']:
            session_times = patterns['pattern_summary']['session_times']

            # Add marker lines for main session if available
            if 'main_session' in session_times:
                main_start = int(session_times['main_session']['start'].split(':')[0])
                main_end = int(session_times['main_session']['end'].split(':')[0])

                if main_end < main_start:  # Handle overnight sessions
                    main_end += 24

                for h in range(main_start, min(main_end, 24)):
                    fig.add_vline(x=h, line_width=1, line_dash="dash", line_color="green", opacity=0.5)

        fig.update_layout(
            title="Pattern Occurrences by Hour and Ticker",
            xaxis_title="Hour of Day",
            yaxis_title="Ticker",
            coloraxis_colorbar_title="Count",
            height=500
        )
        return fig

    return go.Figure().update_layout(title="No data available for heatmap")


# Create bar chart of pattern counts by ticker
def create_ticker_pattern_barchart(pattern_data , selected_tickers=None):
    if not patterns or 'recurring_patterns' not in patterns:
        return go.Figure().update_layout(title="No pattern data available")

    recurring_patterns = pattern_data['recurring_patterns']
    if not recurring_patterns:
        return go.Figure().update_layout(title="No recurring patterns available")

    # Filter by selected tickers if provided
    if selected_tickers:
        recurring_patterns = {ticker: data for ticker, data in recurring_patterns.items()
                              if ticker in selected_tickers}

    if not recurring_patterns:
        return go.Figure().update_layout(title="No patterns for selected tickers")

    # Count patterns by ticker
    ticker_counts = {ticker: len(pattern_data_item) for ticker, pattern_data_item in recurring_patterns.items()}

    # Create dataframe and sort
    df = pd.DataFrame(list(ticker_counts.items()), columns=['Ticker', 'Pattern Count'])
    df = df.sort_values('Pattern Count', ascending=False)

    # Create bar chart
    fig = px.bar(
        df,
        x='Ticker',
        y='Pattern Count',
        color='Pattern Count',
        color_continuous_scale='Viridis',
        title="Number of Patterns by Ticker"
    )

    fig.update_layout(
        xaxis_title="Ticker",
        yaxis_title="Number of Patterns",
        coloraxis_showscale=False,
        height=400
    )

    return fig


# Create pie chart of patterns by trading session
def create_session_distribution_piechart(pattern_data, selected_tickers=None):
    if not pattern_data or 'recurring_patterns' not in pattern_data:
        return go.Figure().update_layout(title="No pattern data available")

    recurring_patterns = pattern_data['recurring_patterns']
    if not recurring_patterns:
        return go.Figure().update_layout(title="No recurring patterns available")

    # Filter by selected tickers if provided
    if selected_tickers:
        recurring_patterns = {ticker: data for ticker, data in recurring_patterns.items()
                              if ticker in selected_tickers}

    if not recurring_patterns:
        return go.Figure().update_layout(title="No patterns for selected tickers")

    # Count patterns by session
    session_counts = {'pre_market': 0, 'main_session': 0, 'post_market': 0, 'after_hours': 0}

    for ticker, ticker_patterns in recurring_patterns.items():
        for time_str, pattern in ticker_patterns.items():
            session = pattern.get('session', 'unknown')
            if session in session_counts:
                session_counts[session] += 1
            else:
                session_counts['after_hours'] += 1

    # Create dataframe
    df = pd.DataFrame(list(session_counts.items()), columns=['Session', 'Count'])
    df = df[df['Count'] > 0]  # Remove zero count sessions

    if df.empty:
        return go.Figure().update_layout(title="No session data available")

    # Create pie chart
    fig = px.pie(
        df,
        values='Count',
        names='Session',
        title="Pattern Distribution by Trading Session",
        color_discrete_sequence=px.colors.sequential.Plasma
    )

    fig.update_traces(textinfo='percent+label')
    fig.update_layout(height=400)

    return fig


def filter_patterns_by_tickers(pattern_data, selected_tickers, pattern_type):
    """Filter pattern data by selected tickers."""
    if not pattern_data:
        return {}

    if not selected_tickers:
        return pattern_data

    if pattern_type in ['recurring_patterns', 'temporal_clusters', 'trend_reversals', 'time_correlations',
                        'time_shifts']:
        return {ticker: data for ticker, data in pattern_data.items() if ticker in selected_tickers}

    return pattern_data


def process_recurring_patterns_for_timeline(selected_patterns):
    """Process recurring patterns data for timeline visualization."""
    rows = []
    for ticker, ticker_patterns in selected_patterns.items():
        for time_str, pattern in ticker_patterns.items():
            time_minutes = time_to_minutes(time_str)
            rows.append({
                'Ticker': ticker,
                'Time': time_str,
                'TimeMinutes': time_minutes,
                'MeanPriceChange': pattern.get('mean_price_change', 0),
                'Consistency': pattern.get('direction_consistency', 0) * 100,
                'Direction': pattern.get('consistent_direction', 'neutral'),
                'PatternType': 'Recurring Pattern',
                'Count': pattern.get('count', 0),
                'PValue': pattern.get('p_value', 1)
            })
    return pd.DataFrame(rows)


def process_temporal_clusters_for_timeline(selected_patterns):
    """Process temporal clusters for timeline visualization."""
    rows = []
    for ticker, clusters in selected_patterns.items():
        for cluster_id, cluster in clusters.items():
            time_str = cluster.get('mean_time', '00:00')
            time_minutes = time_to_minutes(time_str)
            rows.append({
                'Ticker': ticker,
                'Time': time_str,
                'TimeMinutes': time_minutes,
                'MeanPriceImpact': cluster.get('mean_price_impact', 0),
                'StdTimeMinutes': cluster.get('std_time_minutes', 0),
                'Count': cluster.get('count', 0),
                'ClusterId': cluster_id,
                'PatternType': 'Temporal Cluster'
            })
    return pd.DataFrame(rows)

def add_session_reference_lines(fig, pattern_data):
    """Add reference lines for trading sessions to a figure."""
    if 'pattern_summary' in pattern_data and 'session_times' in pattern_data['pattern_summary']:
        session_times = pattern_data['pattern_summary']['session_times']

        # Add marker lines for sessions if available
        sessions = ['pre_market', 'main_session', 'post_market']
        colors = ['blue', 'green', 'purple']

        for session, color in zip(sessions, colors):
            if session in session_times:
                start_time = session_times[session]['start']
                end_time = session_times[session]['end']

                start_minutes = time_to_minutes(start_time)
                end_minutes = time_to_minutes(end_time)

                # Handle overnight sessions
                if end_minutes < start_minutes:
                    end_minutes += 24 * 60

                # Add vertical lines
                fig.add_vline(x=start_minutes, line_width=1, line_dash="dash", line_color=color, opacity=0.5)

                # Only add end line if within 24-hour display
                if end_minutes <= 24 * 60:
                    fig.add_vline(x=end_minutes, line_width=1, line_dash="dash", line_color=color, opacity=0.5)

    return fig


# Create timeline view of patterns
def create_pattern_timeline(pattern_data, selected_tickers=None, selected_pattern_type='recurring_patterns'):
    """
    Create timeline view of patterns.

    Parameters:
    pattern_data (dict): Dictionary of pattern data
    selected_tickers (list): List of selected ticker symbols
    selected_pattern_type (str): Type of pattern to display

    Returns:
    plotly.graph_objects.Figure: Timeline visualization
    """
    if not pattern_data or selected_pattern_type not in pattern_data:
        return go.Figure().update_layout(title=f"No {selected_pattern_type} data available")

    # Filter patterns by selected tickers
    selected_patterns = filter_patterns_by_tickers(pattern_data[selected_pattern_type], selected_tickers,
                                                   selected_pattern_type)

    if not selected_patterns:
        return go.Figure().update_layout(title=f"No {selected_pattern_type} for selected tickers")

    # Create figure
    fig = go.Figure()

    # Process data based on pattern type
    if selected_pattern_type == 'recurring_patterns':
        df = process_recurring_patterns_for_timeline(selected_patterns)

        if df.empty:
            return go.Figure().update_layout(title="No recurring patterns to display")

        # Sort by time
        df = df.sort_values('TimeMinutes')

        # Add trace for each ticker
        for ticker in df['Ticker'].unique():
            ticker_df = df[df['Ticker'] == ticker]

            # Determine color based on consistency
            colors = []
            for _, row in ticker_df.iterrows():
                if row['Direction'] == 'positive':
                    colors.append('green')
                elif row['Direction'] == 'negative':
                    colors.append('red')
                else:
                    colors.append('gray')

            # Add scatter plot
            fig.add_trace(go.Scatter(
                x=ticker_df['TimeMinutes'],
                y=[ticker] * len(ticker_df),
                mode='markers',
                marker=dict(
                    size=ticker_df['Consistency'] / 5 + 5,  # Size based on consistency
                    color=colors,
                    symbol='circle',
                    opacity=0.8,
                    line=dict(width=1, color='white')
                ),
                text=[
                    f"Ticker: {row['Ticker']}<br>"
                    f"Time: {row['Time']}<br>"
                    f"Mean Price Change: {row['MeanPriceChange']:.2f}%<br>"
                    f"Consistency: {row['Consistency']:.1f}%<br>"
                    f"Direction: {row['Direction']}<br>"
                    f"Count: {row['Count']}<br>"
                    f"p-value: {row['PValue']:.3f}"
                    for _, row in ticker_df.iterrows()
                ],
                hoverinfo='text',
                name=ticker
            ))

    elif selected_pattern_type == 'temporal_clusters':
        df = process_temporal_clusters_for_timeline(selected_patterns)

        if df.empty:
            return go.Figure().update_layout(title="No temporal clusters to display")

        # Sort by time
        df = df.sort_values('TimeMinutes')

        # Add trace for each ticker
        for ticker in df['Ticker'].unique():
            ticker_df = df[df['Ticker'] == ticker]

            # Determine color based on price impact
            colors = []
            for _, row in ticker_df.iterrows():
                if row['MeanPriceImpact'] > 0:
                    colors.append('green')
                elif row['MeanPriceImpact'] < 0:
                    colors.append('red')
                else:
                    colors.append('gray')

            # Add scatter plot
            fig.add_trace(go.Scatter(
                x=ticker_df['TimeMinutes'],
                y=[ticker] * len(ticker_df),
                mode='markers',
                marker=dict(
                    size=ticker_df['Count'] + 5,  # Size based on count
                    color=colors,
                    symbol='square',
                    opacity=0.8,
                    line=dict(width=1, color='white')
                ),
                text=[
                    f"Ticker: {row['Ticker']}<br>"
                    f"Time: {row['Time']}<br>"
                    f"Mean Price Impact: {row['MeanPriceImpact']:.2f}%<br>"
                    f"Time Std Dev: {row['StdTimeMinutes']:.1f} min<br>"
                    f"Count: {row['Count']}<br>"
                    f"Cluster ID: {row['ClusterId']}"
                    for _, row in ticker_df.iterrows()
                ],
                hoverinfo='text',
                name=ticker
            ))

    # Implement other pattern types similarly...

    # Add reference lines for trading sessions
    add_session_reference_lines(fig, pattern_data)

    # Update layout
    fig.update_layout(
        title=f"{selected_pattern_type.replace('_', ' ').title()} Timeline",
        xaxis=dict(
            title="Time of Day",
            tickmode='array',
            tickvals=list(range(0, 24 * 60 + 1, 60)),
            ticktext=[f"{h:02d}:00" for h in range(25)],
            range=[0, 24 * 60]
        ),
        yaxis=dict(
            title="Ticker",
            categoryorder='category ascending'
        ),
        height=500,
        hovermode='closest'
    )

    return fig

# Create time correlation network graph
def create_time_correlation_network(pattern_data, selected_ticker=None):
    """
    Create a network graph visualization of time correlations between market patterns.

    This function builds a network where:
    - Nodes represent specific times for a ticker
    - Edges represent correlations between times
    - Edge color indicates positive (green) or negative (red) correlation
    - Edge width represents correlation strength
    - Only statistically significant correlations (p < 0.05) are shown

    Parameters:
    -----------
    pattern_data : dict
        Dictionary containing all pattern data including time_correlations
    selected_ticker : str, optional
        If provided, only show correlations for this ticker

    Returns:
    --------
    plotly.graph_objects.Figure
        Network visualization of time correlations
    """
    if not pattern_data or 'time_correlations' not in pattern_data:
        return go.Figure().update_layout(title="No time correlation data available")

    time_correlations = patterns['time_correlations']
    if not time_correlations:
        return go.Figure().update_layout(title="No time correlations available")

    # Filter by selected ticker if provided
    if selected_ticker and selected_ticker in time_correlations:
        time_correlations = {selected_ticker: time_correlations[selected_ticker]}
    elif selected_ticker:
        return go.Figure().update_layout(title=f"No time correlations for {selected_ticker}")

    if not time_correlations:
        return go.Figure().update_layout(title="No time correlations for selected ticker")

    # Create network graph
    g = nx.Graph()

    # Add nodes and edges
    for ticker, correlations in time_correlations.items():
        for correlation in correlations:
            time1 = correlation.get('time1', '00:00')
            time2 = correlation.get('time2', '00:00')
            corr_value = correlation.get('correlation', 0)
            p_value = correlation.get('p_value', 1)
            sample_size = correlation.get('sample_size', 0)

            # Only include significant correlations
            if p_value < 0.05:
                node1 = f"{ticker}_{time1}"
                node2 = f"{ticker}_{time2}"

                # Add nodes if they don't exist
                if node1 not in g:
                    g.add_node(node1, time=time1, ticker=ticker, type='time')
                if node2 not in g:
                    g.add_node(node2, time=time2, ticker=ticker, type='time')

                # Add edge
                g.add_edge(node1, node2, weight=abs(corr_value), correlation=corr_value,
                           p_value=p_value, sample_size=sample_size, color='red' if corr_value < 0 else 'green')

    # Check if graph is empty
    if not g.nodes:
        return go.Figure().update_layout(title="No significant time correlations found")

    # Use spring layout for node positions
    pos = nx.spring_layout(g, seed=42)

    # Create edge trace
    edge_x = []
    edge_y = []
    edge_colors = []
    edge_widths = []

    for edge in g.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

        edge_data = g.get_edge_data(edge[0], edge[1])
        edge_colors.append(edge_data['color'])
        edge_widths.append(edge_data['weight'] * 2)

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=edge_widths, color=edge_colors),
        hoverinfo='none',
        mode='lines'
    )

    # Create node trace
    node_x = []
    node_y = []
    node_text = []
    node_colors = []

    for node in g.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)

        node_data = g.nodes[node]
        ticker = node_data['ticker']
        time = node_data['time']

        node_text.append(f"{ticker} - {time}")

        # Color by ticker
        node_colors.append(hash(ticker) % 256)

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode='markers',
        hoverinfo='text',
        text=node_text,
        marker=dict(
            showscale=True,
            colorscale='Viridis',
            color=node_colors,
            size=10,
            line=dict(width=2, color='white')
        )
    )

    # Create figure
    fig = go.Figure(data=[edge_trace, node_trace],
                    layout=go.Layout(
                        title="Time Correlation Network",
                        showlegend=False,
                        hovermode='closest',
                        margin=dict(b=20, l=5, r=5, t=40),
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        height=600
                    ))

    return fig


# Dashboard Layout
def create_layout(pattern_data):
    # Get available tickers from pattern data using cached function
    available_tickers = get_available_tickers(pattern_data)
    if pattern_data and 'recurring_patterns' in pattern_data:
        available_tickers = list(pattern_data['recurring_patterns'].keys())

    # Main layout
    return html.Div([
        # Header
        html.Div([
            html.H1("Market Pattern Analysis Dashboard", className="display-4 text-center mb-4"),
            html.P("Interactive visualization of detected market patterns", className="lead text-center")
        ], className="jumbotron p-4 bg-dark text-white"),

        # Global filters
        dbc.Card([
            dbc.CardHeader("Global Filters"),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.Label("Select Tickers:", className="d-inline-block mr-1"),
                            html.I(className="fas fa-question-circle", id="ticker-help",
                                   style={"marginLeft": "5px", "cursor": "pointer"})
                        ]),
                        dbc.Tooltip(
                            "Select one or more tickers to filter the patterns displayed in all visualizations. "
                            "Multiple tickers can be selected for comparison.",
                            target="ticker-help",
                        ),
                        dcc.Dropdown(
                            id='ticker-selector',
                            options=[{'label': ticker, 'value': ticker} for ticker in available_tickers],
                            value=available_tickers[:3] if len(available_tickers) >= 3 else available_tickers,
                            multi=True,
                            placeholder="Select tickers..."
                        )
                    ], width=6),
                    dbc.Col([
                        html.Div([
                            html.Label("Pattern Type:", className="d-inline-block mr-1"),
                            html.I(className="fas fa-question-circle", id="pattern-type-help",
                                   style={"marginLeft": "5px", "cursor": "pointer"})
                        ]),
                        dbc.Tooltip(
                            "Choose the type of market pattern to visualize: "
                            "Recurring Patterns (regular price movements), "
                            "Temporal Clusters (groups of events), "
                            "Trend Reversals (direction changes), "
                            "Time Correlations (related times), or "
                            "Time-Shifted Patterns (similar patterns at different times).",
                            target="pattern-type-help",
                        ),
                        dcc.Dropdown(
                            id='pattern-type-selector',
                            options=[
                                {'label': 'Recurring Patterns', 'value': 'recurring_patterns'},
                                {'label': 'Temporal Clusters', 'value': 'temporal_clusters'},
                                {'label': 'Trend Reversals', 'value': 'trend_reversals'},
                                {'label': 'Time Correlations', 'value': 'time_correlations'},
                                {'label': 'Time-Shifted Patterns', 'value': 'time_shifts'}
                            ],
                            value='recurring_patterns',
                            clearable=False
                        )
                    ], width=6)
                ])
            ])
        ], className="mb-4"),

        # Tabs for different views
        dbc.Tabs([
            # Overview Tab
            dbc.Tab(label="Overview", children=[
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.H4("How to Use This Dashboard", className="mb-3"),
                            html.P([
                                "This dashboard visualizes patterns in financial market data. ",
                                "Use the filters above to select tickers and pattern types of interest."
                            ]),
                            html.Ul([
                                html.Li("Overview: High-level summary of pattern distributions"),
                                html.Li("Pattern Timeline: Detailed view of patterns over time"),
                                html.Li("Pattern Comparison: Compare patterns across different metrics"),
                                html.Li("Advanced Analysis: Network visualizations and deeper analysis"),
                                html.Li("Pattern Annotations: Add notes to patterns for future reference")
                            ]),
                            html.P("Click on patterns in visualizations to see additional details.")
                        ], className="p-3 bg-light text-dark rounded mb-4")
                    ], width=12),

                    # Summary statistics (existing code)
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader("Pattern Summary"),
                            dbc.CardBody(id="pattern-summary-card")
                        ], className="mb-4"),
                    ], width=12),

                    # Pattern distribution by hour and ticker
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader("Pattern Distribution"),
                            dbc.CardBody([
                                dcc.Graph(id="pattern-heatmap")
                            ])
                        ])
                    ], width=8),

                    # Pattern distribution by session
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader("Session Distribution"),
                            dbc.CardBody([
                                dcc.Graph(id="session-piechart")
                            ])
                        ], className="mb-4"),

                        dbc.Card([
                            dbc.CardHeader("Patterns by Ticker"),
                            dbc.CardBody([
                                dcc.Graph(id="ticker-barchart")
                            ])
                        ])
                    ], width=4)
                ])
            ]),

            # Timeline View Tab
            dbc.Tab(label="Pattern Timeline", children=[
                dbc.Card([
                    dbc.CardHeader("Pattern Timeline View"),
                    dbc.CardBody([
                        dcc.Graph(id="pattern-timeline", style={"height": "600px"})
                    ])
                ], className="mb-4"),

                dbc.Card([
                    dbc.CardHeader("Pattern Details"),
                    dbc.CardBody(id="pattern-detail-panel", children=[
                        html.P("Click on a pattern in the timeline to see details.", className="text-muted")
                    ])
                ])
            ]),

            # Pattern Comparison Tab
            dbc.Tab(label="Pattern Comparison", children=[
                dbc.Row([
                    dbc.Col([
                        html.Label("Select Comparison Metric:"),
                        dcc.Dropdown(
                            id='comparison-metric-selector',
                            options=[
                                {'label': 'Mean Price Change', 'value': 'mean_price_change'},
                                {'label': 'Consistency', 'value': 'direction_consistency'},
                                {'label': 'Pattern Count', 'value': 'count'},
                                {'label': 'Statistical Significance', 'value': 'p_value'}
                            ],
                            value='mean_price_change',
                            clearable=False
                        )
                    ], width=6),
                    dbc.Col([
                        html.Label("Sort By:"),
                        dcc.RadioItems(
                            id='sort-order-selector',
                            options=[
                                {'label': 'Ascending', 'value': 'asc'},
                                {'label': 'Descending', 'value': 'desc'}
                            ],
                            value='desc',
                            inputStyle={"marginRight": "10px"},
                            labelStyle={"marginRight": "20px"},
                            className="d-flex"
                        )
                    ], width=6)
                ], className="mb-3"),

                dbc.Card([
                    dbc.CardHeader("Pattern Comparison by Ticker"),
                    dbc.CardBody([
                        dcc.Graph(id="pattern-comparison-chart")
                    ])
                ], className="mb-4"),

                dbc.Card([
                    dbc.CardHeader("Comparison Data Table"),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id="comparison-data-table",
                            style_table={'overflowX': 'auto'},
                            style_cell={
                                'backgroundColor': '#303030',
                                'color': 'white',
                                'textAlign': 'left'
                            },
                            style_header={
                                'backgroundColor': '#404040',
                                'fontWeight': 'bold'
                            },
                            page_size=10
                        )
                    ])
                ])
            ]),

            # Advanced Analysis Tab
            dbc.Tab(label="Advanced Analysis", children=[
                dbc.Row([
                    dbc.Col([
                        html.Label("Select Analysis View:"),
                        dcc.RadioItems(
                            id='advanced-analysis-selector',
                            options=[
                                {'label': 'Time Correlation Network', 'value': 'correlation_network'},
                                {'label': 'Time-Shifted Patterns', 'value': 'time_shifts'},
                                {'label': 'Trend Reversals Chart', 'value': 'trend_reversals'}
                            ],
                            value='correlation_network',
                            inputStyle={"marginRight": "10px"},
                            labelStyle={"marginRight": "20px"},
                            className="d-flex"
                        )
                    ], width=6),
                    dbc.Col([
                        html.Label("Select Ticker for Detailed Analysis:"),
                        dcc.Dropdown(
                            id='advanced-ticker-selector',
                            options=[{'label': ticker, 'value': ticker} for ticker in available_tickers],
                            value=available_tickers[0] if available_tickers else None,
                            clearable=False
                        )
                    ], width=6)
                ], className="mb-3"),

                dbc.Card([
                    dbc.CardHeader(id="advanced-analysis-header"),
                    dbc.CardBody([
                        dcc.Graph(id="advanced-analysis-chart", style={"height": "600px"})
                    ])
                ], className="mb-4"),

                dbc.Card([
                    dbc.CardHeader("Analysis Details"),
                    dbc.CardBody(id="advanced-analysis-details", children=[
                        html.P("Select an analysis view and ticker to see detailed information.", className="text-muted")
                    ])
                ])
            ]),

            # Pattern Annotations Tab
            dbc.Tab(label="Pattern Annotations", children=[
                dbc.Card([
                    dbc.CardHeader("Pattern Annotations"),
                    dbc.CardBody([
                        html.P("Add, view, and edit annotations for detected patterns."),
                        dbc.Row([
                            dbc.Col([
                                html.Label("Select Ticker:"),
                                dcc.Dropdown(
                                    id='annotation-ticker-selector',
                                    options=[{'label': ticker, 'value': ticker} for ticker in available_tickers],
                                    value=available_tickers[0] if available_tickers else None,
                                    clearable=False
                                )
                            ], width=4),
                            dbc.Col([
                                html.Label("Select Pattern Type:"),
                                dcc.Dropdown(
                                    id='annotation-pattern-type-selector',
                                    options=[
                                        {'label': 'Recurring Patterns', 'value': 'recurring_patterns'},
                                        {'label': 'Temporal Clusters', 'value': 'temporal_clusters'},
                                        {'label': 'Trend Reversals', 'value': 'trend_reversals'}
                                    ],
                                    value='recurring_patterns',
                                    clearable=False
                                )
                            ], width=4),
                            dbc.Col([
                                html.Label("Available Patterns:"),
                                dcc.Dropdown(id='annotation-pattern-selector', clearable=False)
                            ], width=4)
                        ], className="mb-3"),

                        dbc.Card([
                            dbc.CardHeader("Pattern Annotation"),
                            dbc.CardBody([
                                dbc.Row([
                                    dbc.Col([
                                        html.Label("Pattern Details:"),
                                        html.Div(id="annotation-pattern-details", className="p-3 bg-dark rounded")
                                    ], width=6),
                                    dbc.Col([
                                        html.Label("Annotation:"),
                                        dbc.Textarea(
                                            id="annotation-text",
                                            placeholder="Enter explanation for this pattern...",
                                            style={"height": "150px"}
                                        ),
                                        html.Div([
                                            dbc.Button("Save Annotation", id="save-annotation-button",
                                                    color="primary", className="me-2 mt-2"),
                                            dbc.Button("Delete Annotation", id="delete-annotation-button",
                                                    color="danger", className="mt-2")
                                        ])
                                    ], width=6)
                                ])
                            ])
                        ], className="mb-3"),

                        dbc.Card([
                            dbc.CardHeader("All Annotations"),
                            dbc.CardBody([
                                dash_table.DataTable(
                                    id="all-annotations-table",
                                    columns=[
                                        {"name": "Ticker", "id": "ticker"},
                                        {"name": "Pattern Type", "id": "pattern_type"},
                                        {"name": "Pattern Time", "id": "pattern_time"},
                                        {"name": "Explanation", "id": "explanation"},
                                        {"name": "Last Updated", "id": "updated_at"}
                                    ],
                                    style_table={'overflowX': 'auto'},
                                    style_cell={
                                        'backgroundColor': '#303030',
                                        'color': 'white',
                                        'textAlign': 'left',
                                        'minWidth': '100px',
                                        'maxWidth': '400px',
                                        'whiteSpace': 'normal',
                                        'textOverflow': 'ellipsis'
                                    },
                                    style_header={
                                        'backgroundColor': '#404040',
                                        'fontWeight': 'bold'
                                    },
                                    page_size=10,
                                    filter_action="native",
                                    sort_action="native"
                                )
                            ])
                        ])
                    ])
                ])
            ])
        ], className="mt-4")
    ])

@callback(
    Output("pattern-summary-card", "children"),
     Input("ticker-selector", "value")
)

def update_summary_card(selected_tickers):
    if not patterns or 'pattern_summary' not in patterns:
        return html.P("No pattern summary data available")

    summary = patterns['pattern_summary']

    # Filter summary data based on selected tickers if applicable
    if selected_tickers and 'pattern_count_by_ticker' in summary:
        total_patterns = sum(summary['pattern_count_by_ticker'].get(ticker, 0) for ticker in selected_tickers)
    else:
        total_patterns = summary.get('total_patterns', 0)

    # Create summary cards
    return dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4(f"{total_patterns}", className="card-title text-center"),
                    html.P("Total Patterns", className="card-text text-center")
                ])
            ], color="primary", inverse=True)
        ], width=3),

        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4(f"{len(selected_tickers) if selected_tickers else 0}", className="card-title text-center"),
                    html.P("Selected Tickers", className="card-text text-center")
                ])
            ], color="secondary", inverse=True)
        ], width=3),

        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4(f"{summary.get('pattern_count_by_session', {}).get('main_session', 0)}",
                            className="card-title text-center"),
                    html.P("Main Session Patterns", className="card-text text-center")
                ])
            ], color="success", inverse=True)
        ], width=3),

        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4(
                        f"{summary.get('patterns_by_hour', {}).get('9', 0) + summary.get('patterns_by_hour', {}).get('16', 0)}",
                        className="card-title text-center"),
                    html.P("Market Open/Close Patterns", className="card-text text-center")
                ])
            ], color="info", inverse=True)
        ], width=3)
    ])


@callback(
    Output("pattern-heatmap", "figure"),
    Input("ticker-selector", "value")
)
def update_pattern_heatmap(selected_tickers):
    filtered_data = get_filtered_pattern_data(patterns, 'recurring_patterns', selected_tickers)
    return create_pattern_heatmap(patterns, selected_tickers)


@callback(
    Output("ticker-barchart", "figure"),
    Input("ticker-selector", "value")
)
def update_ticker_barchart(selected_tickers):
    return create_ticker_pattern_barchart(patterns, selected_tickers)


@callback(
    Output("session-piechart", "figure"),
    Input("ticker-selector", "value")
)
def update_session_piechart(selected_tickers):
    return create_session_distribution_piechart(patterns, selected_tickers)


@callback(
    Output("pattern-timeline", "figure"),
    Input("ticker-selector", "value"),
    Input("pattern-type-selector", "value")
)
def update_pattern_timeline(selected_tickers, selected_pattern_type):
    return create_pattern_timeline(patterns, selected_tickers, selected_pattern_type)


@callback(
    Output("pattern-detail-panel", "children"),
    Input("pattern-timeline", "clickData"),
    Input("ticker-selector", "value"),
    Input("pattern-type-selector", "value")
)
def update_pattern_details(click_data, pattern_type):
    if not click_data:
        return html.P("Click on a pattern in the timeline to see details.", className="text-muted")

    try:
        # Extract information from the clicked point
        point_data = click_data['points'][0]
        ticker = point_data['y']
        time_minutes = point_data['x']
        time_str = minutes_to_time(time_minutes)

        # Find the pattern information
        if pattern_type == 'recurring_patterns':
            if ticker in patterns['recurring_patterns'] and time_str in patterns['recurring_patterns'][ticker]:
                pattern = patterns['recurring_patterns'][ticker][time_str]

                # Get annotation if exists
                annotation = get_pattern_annotation(ticker, pattern_type, time_str)

                # Create detail cards
                return [
                    dbc.Row([
                        dbc.Col([
                            html.H4(f"{ticker} - {time_str}", className="card-title"),
                            html.P(f"Session: {pattern.get('session', 'Unknown')}", className="card-text"),
                            html.P(f"Count: {pattern.get('count', 0)} observations", className="card-text"),
                            html.P(f"Mean Price Change: {pattern.get('mean_price_change', 0):.2f}%",
                                   className="card-text"),
                            html.P(f"Direction Consistency: {pattern.get('direction_consistency', 0) * 100:.1f}%",
                                   className="card-text"),
                            html.P(f"Direction: {pattern.get('consistent_direction', 'neutral')}",
                                   className="card-text"),
                            html.P(f"p-value: {pattern.get('p_value', 1):.4f}", className="card-text")
                        ], width=6),
                        dbc.Col([
                            html.H5("Annotation:", className="card-title"),
                            html.P(annotation if annotation else "No annotation available."),
                            html.H5("Dates Observed:", className="card-title mt-3"),
                            html.Div([
                                html.P(date, className="badge bg-secondary m-1")
                                for date in pattern.get('dates_observed', [])[:10]
                            ])
                        ], width=6)
                    ])
                ]

        elif pattern_type == 'temporal_clusters':
            if ticker in patterns['temporal_clusters']:
                # Find the cluster that matches the time
                for cluster_id, cluster in patterns['temporal_clusters'][ticker].items():
                    cluster_time = cluster.get('mean_time', '00:00')
                    cluster_minutes = time_to_minutes(cluster_time)

                    # Allow some tolerance for clicking
                    if abs(cluster_minutes - time_minutes) < 15:
                        # Get annotation if exists
                        annotation = get_pattern_annotation(ticker, pattern_type, cluster_time)

                        # Get events for the cluster
                        events = cluster.get('events', [])

                        return [
                            dbc.Row([
                                dbc.Col([
                                    html.H4(f"{ticker} - Cluster at {cluster_time}", className="card-title"),
                                    html.P(f"Cluster ID: {cluster_id}", className="card-text"),
                                    html.P(f"Count: {cluster.get('count', 0)} events", className="card-text"),
                                    html.P(f"Mean Price Impact: {cluster.get('mean_price_impact', 0):.2f}%",
                                           className="card-text"),
                                    html.P(f"Std Dev Time: {cluster.get('std_time_minutes', 0):.1f} minutes",
                                           className="card-text"),
                                    html.P(f"Std Dev Price: {cluster.get('std_price_impact', 0):.2f}%",
                                           className="card-text"),
                                    html.P(
                                        f"Statistically Significant: {cluster.get('is_statistically_significant', False)}",
                                        className="card-text")
                                ], width=6),
                                dbc.Col([
                                    html.H5("Annotation:", className="card-title"),
                                    html.P(annotation if annotation else "No annotation available."),
                                    html.H5("Sample Events:", className="card-title mt-3"),
                                    html.Div([
                                        html.P(
                                            f"{event.get('Date', 'Unknown')} ({event.get('TimeString', 'Unknown')}): {event.get('PriceChange', 0):.2f}%",
                                            className="badge bg-secondary m-1")
                                        for event in events[:5]
                                    ])
                                ], width=6)
                            ])
                        ]

        elif pattern_type == 'trend_reversals':
            if ticker in patterns['trend_reversals']:
                # Find the reversal that matches the time
                for reversal in patterns['trend_reversals'][ticker]:
                    reversal_time = reversal.get('time', '00:00')
                    reversal_minutes = time_to_minutes(reversal_time)

                    # Allow some tolerance for clicking
                    if abs(reversal_minutes - time_minutes) < 15:
                        # Get annotation if exists
                        annotation = get_pattern_annotation(ticker, pattern_type, reversal_time)

                        return [
                            dbc.Row([
                                dbc.Col([
                                    html.H4(f"{ticker} - Reversal at {reversal_time}", className="card-title"),
                                    html.P(f"Reversal Type: {reversal.get('reversal_type', 'Unknown')}",
                                           className="card-text"),
                                    html.P(f"Price Change: {reversal.get('price_change_pct', 0):.2f}%",
                                           className="card-text"),
                                    html.P(f"Duration: {reversal.get('duration_minutes', 0):.1f} minutes",
                                           className="card-text"),
                                    html.P(f"Volume Ratio: {reversal.get('volume_ratio', 1):.2f}",
                                           className="card-text"),
                                    html.P(f"Date: {reversal.get('datetime', 'Unknown')}", className="card-text")
                                ], width=6),
                                dbc.Col([
                                    html.H5("Annotation:", className="card-title"),
                                    html.P(annotation if annotation else "No annotation available.")
                                ], width=6)
                            ])
                        ]

        # If we get here, pattern wasn't found
        return html.P(f"Could not find detailed information for {ticker} at {time_str}", className="text-danger")

    except Exception as e:
        return html.P(f"Error retrieving pattern details: {str(e)}", className="text-danger")


@callback(
    Output("pattern-comparison-chart", "figure"),
    Output("comparison-data-table", "data"),
    Output("comparison-data-table", "columns"),
    Input("ticker-selector", "value"),
    Input("pattern-type-selector", "value"),
    Input("comparison-metric-selector", "value"),
    Input("sort-order-selector", "value")
)
def update_pattern_comparison(selected_tickers, pattern_type, comparison_metric, sort_order):
    if not patterns or pattern_type not in patterns:
        return go.Figure().update_layout(title=f"No {pattern_type} data available"), [], []

    pattern_data = patterns[pattern_type]
    if not pattern_data:
        return go.Figure().update_layout(title=f"No {pattern_type} data available"), [], []

    # Filter by selected tickers
    if selected_tickers:
        pattern_data = {ticker: data for ticker, data in pattern_data.items() if ticker in selected_tickers}

    if not pattern_data:
        return go.Figure().update_layout(title=f"No {pattern_type} for selected tickers"), [], []

    # Process data based on pattern type
    if pattern_type == 'recurring_patterns':
        rows = []
        for ticker, ticker_patterns in pattern_data.items():
            for time_str, pattern in ticker_patterns.items():
                row = {
                    'Ticker': ticker,
                    'Time': time_str,
                    'Mean Price Change': pattern.get('mean_price_change', 0),
                    'Direction Consistency': pattern.get('direction_consistency', 0) * 100,
                    'Count': pattern.get('count', 0),
                    'p-value': pattern.get('p_value', 1),
                    'Direction': pattern.get('consistent_direction', 'neutral'),
                    'Session': pattern.get('session', 'unknown')
                }
                rows.append(row)

        df = pd.DataFrame(rows)

        if df.empty:
            return go.Figure().update_layout(title="No data available for comparison"), [], []

        # Convert metric names to column names
        metric_col_map = {
            'mean_price_change': 'Mean Price Change',
            'direction_consistency': 'Direction Consistency',
            'count': 'Count',
            'p_value': 'p-value'
        }

        metric_col = metric_col_map.get(comparison_metric, 'Mean Price Change')

        # Sort data
        df = df.sort_values(by=[metric_col], ascending=(sort_order == 'asc'))

        # Create figure
        fig = px.bar(
            df,
            x='Ticker',
            y=metric_col,
            color='Direction',
            facet_row='Session',
            hover_data=['Time', 'Mean Price Change', 'Direction Consistency', 'Count', 'p-value'],
            color_discrete_map={'positive': 'green', 'negative': 'red', 'neutral': 'gray'},
            title=f"Pattern Comparison by {metric_col}",
            height=600
        )

        fig.update_layout(
            xaxis_title="Ticker",
            yaxis_title=metric_col,
            legend_title="Price Direction"
        )

        # Prepare data table
        table_data = df.to_dict('records')
        columns = [{"name": col, "id": col} for col in df.columns]

        return fig, table_data, columns

    elif pattern_type == 'temporal_clusters':
        rows = []
        for ticker, clusters in pattern_data.items():
            for cluster_id, cluster in clusters.items():
                row = {
                    'Ticker': ticker,
                    'Cluster ID': cluster_id,
                    'Mean Time': cluster.get('mean_time', '00:00'),
                    'Mean Price Impact': cluster.get('mean_price_impact', 0),
                    'Count': cluster.get('count', 0),
                    'Std Dev Time': cluster.get('std_time_minutes', 0),
                    'Std Dev Price': cluster.get('std_price_impact', 0),
                    'Significant': 'Yes' if cluster.get('is_statistically_significant', False) else 'No'
                }
                rows.append(row)

        df = pd.DataFrame(rows)

        if df.empty:
            return go.Figure().update_layout(title="No data available for comparison"), [], []

        # Convert metric names to column names
        metric_col_map = {
            'mean_price_change': 'Mean Price Impact',
            'direction_consistency': 'Count',  # Use count instead
            'count': 'Count',
            'p_value': 'Std Dev Price'  # Use std dev instead
        }

        metric_col = metric_col_map.get(comparison_metric, 'Mean Price Impact')

        # Sort data
        df = df.sort_values(by=[metric_col], ascending=(sort_order == 'asc'))

        # Create figure
        fig = px.bar(
            df,
            x='Ticker',
            y=metric_col,
            color='Significant',
            hover_data=['Mean Time', 'Mean Price Impact', 'Count', 'Std Dev Time', 'Std Dev Price'],
            color_discrete_map={'Yes': 'green', 'No': 'gray'},
            title=f"Cluster Comparison by {metric_col}",
            height=600
        )

        fig.update_layout(
            xaxis_title="Ticker",
            yaxis_title=metric_col,
            legend_title="Statistically Significant"
        )

        # Prepare data table
        table_data = df.to_dict('records')
        columns = [{"name": col, "id": col} for col in df.columns]

        return fig, table_data, columns

    # Default return
    return go.Figure().update_layout(title="Select pattern type for comparison"), [], []


@callback(
    Output("advanced-analysis-header", "children"),
    Output("advanced-analysis-chart", "figure"),
    Output("advanced-analysis-details", "children"),
    Input("advanced-analysis-selector", "value"),
    Input("advanced-ticker-selector", "value")
)
def update_advanced_analysis(analysis_type, selected_ticker):
    if not patterns:
        return "No data available", go.Figure(), html.P("No data available for analysis.")

    if analysis_type == 'correlation_network':
        title = "Time Correlation Network"
        fig = create_time_correlation_network(patterns, selected_ticker)

        # Get correlation details
        details = html.P(
            "Time correlation network shows relationships between market patterns occurring at different times of day.")

        if selected_ticker and 'time_correlations' in patterns and selected_ticker in patterns['time_correlations']:
            correlations = patterns['time_correlations'][selected_ticker]

            if correlations:
                correlation_items = []
                for correlation in sorted(correlations, key=lambda x: abs(x.get('correlation', 0)), reverse=True)[:10]:
                    time1 = correlation.get('time1', '00:00')
                    time2 = correlation.get('time2', '00:00')
                    corr_value = correlation.get('correlation', 0)
                    p_value = correlation.get('p_value', 1)

                    item = html.Li([
                        f"{time1} ↔ {time2}: ",
                        html.Span(
                            f"{corr_value:.2f}",
                            style={'color': 'red' if corr_value < 0 else 'green'}
                        ),
                        f" (p-value: {p_value:.4f})"
                    ])
                    correlation_items.append(item)

                details = [
                    html.P("Strongest time correlations:"),
                    html.Ul(correlation_items)
                ]

        return title, fig, details

    elif analysis_type == 'time_shifts':
        title = "Time-Shifted Patterns"

        if 'time_shifts' not in patterns or not selected_ticker or selected_ticker not in patterns['time_shifts']:
            return title, go.Figure().update_layout(title="No time-shifted patterns available"), html.P(
                "No time-shifted pattern data available for the selected ticker.")

        time_shifts = patterns['time_shifts'][selected_ticker]

        if not time_shifts:
            return title, go.Figure().update_layout(title="No time-shifted patterns available"), html.P(
                "No time-shifted pattern data available for the selected ticker.")

        # Create visualization for time-shifted patterns
        fig = go.Figure()

        for idx, shift in enumerate(time_shifts):
            if isinstance(shift, dict) and 'shifts' in shift:
                # This is a cluster of shifts
                cluster = shift
                shifts = cluster.get('shifts', [])

                # Add a trace for each shift in the cluster
                for i, s in enumerate(shifts):
                    early_time = s.get('earlier_time', '00:00')
                    late_time = s.get('later_time', '00:00')
                    early_minutes = time_to_minutes(early_time)
                    late_minutes = time_to_minutes(late_time)

                    # Add line connecting the two times
                    fig.add_trace(go.Scatter(
                        x=[early_minutes, late_minutes],
                        y=[idx, idx],
                        mode='lines+markers',
                        marker=dict(size=8, symbol='circle'),
                        line=dict(width=1, dash='solid', color=f'rgba(100, 149, 237, {0.5 + 0.5 * i / len(shifts)})'),
                        name=f"Cluster {idx} - Shift {i}",
                        text=[early_time, late_time],
                        hoverinfo='text',
                        showlegend=False
                    ))

                # Add a trace for the average shift
                avg_early = cluster.get('avg_earlier_time_minutes', 0)
                avg_late = cluster.get('avg_later_time_minutes', 0)
                avg_early_str = cluster.get('avg_earlier_time', '00:00')
                avg_late_str = cluster.get('avg_later_time', '00:00')

                fig.add_trace(go.Scatter(
                    x=[avg_early, avg_late],
                    y=[idx, idx],
                    mode='lines+markers',
                    marker=dict(size=12, symbol='square'),
                    line=dict(width=3, dash='solid', color='rgb(65, 105, 225)'),
                    name=f"Cluster {idx} Average",
                    text=[
                        f"Average earlier time: {avg_early_str}<br>"
                        f"Count: {cluster.get('count', 0)}<br>"
                        f"Time diff: {cluster.get('avg_time_diff_minutes', 0):.1f} min",

                        f"Average later time: {avg_late_str}<br>"
                        f"Count: {cluster.get('count', 0)}<br>"
                        f"Time diff: {cluster.get('avg_time_diff_minutes', 0):.1f} min"
                    ],
                    hoverinfo='text'
                ))

        # Update layout
        fig.update_layout(
            title=f"Time-Shifted Patterns for {selected_ticker}",
            xaxis=dict(
                title="Time of Day (minutes since midnight)",
                tickmode='array',
                tickvals=list(range(0, 24 * 60 + 1, 60)),
                ticktext=[f"{h:02d}:00" for h in range(25)],
                range=[0, 24 * 60]
            ),
            yaxis=dict(
                title="Pattern Cluster",
                showticklabels=False
            ),
            height=600,
            hovermode='closest'
        )

        # Add reference lines for trading sessions if available
        if 'pattern_summary' in patterns and 'session_times' in patterns['pattern_summary']:
            session_times = patterns['pattern_summary']['session_times']

            # Add marker lines for sessions if available
            sessions = ['pre_market', 'main_session', 'post_market']
            colors = ['blue', 'green', 'purple']

            for session, color in zip(sessions, colors):
                if session in session_times:
                    start_time = session_times[session]['start']
                    end_time = session_times[session]['end']

                    start_minutes = time_to_minutes(start_time)
                    end_minutes = time_to_minutes(end_time)

                    # Handle overnight sessions
                    if end_minutes < start_minutes:
                        end_minutes += 24 * 60

                    # Add vertical lines
                    fig.add_vline(x=start_minutes, line_width=1, line_dash="dash", line_color=color, opacity=0.5)
                    if end_minutes <= 24 * 60:
                        fig.add_vline(x=end_minutes, line_width=1, line_dash="dash", line_color=color, opacity=0.5)

        # Create detail text
        details = []
        for idx, shift in enumerate(time_shifts):
            if isinstance(shift, dict) and 'shifts' in shift:
                cluster = shift
                shifts_count = len(cluster.get('shifts', []))
                avg_diff = cluster.get('avg_time_diff_minutes', 0)
                early_time = cluster.get('avg_earlier_time', '00:00')
                late_time = cluster.get('avg_later_time', '00:00')

                details.append(html.P([
                    html.Strong(f"Cluster {idx}: "),
                    f"{shifts_count} shifts, {early_time} → {late_time} ",
                    f"(avg diff: {avg_diff:.1f} min)"
                ]))

        if not details:
            details = [html.P("No detailed information available.")]

        details = [html.P("Time-shifted patterns indicate when similar market behaviors occur at different times."),
                   html.Hr()] + details

        return title, fig, details

    elif analysis_type == 'trend_reversals':
        title = "Trend Reversals"

        if 'trend_reversals' not in patterns or not selected_ticker or selected_ticker not in patterns[
            'trend_reversals']:
            return title, go.Figure().update_layout(title="No trend reversal data available"), html.P(
                "No trend reversal data available for the selected ticker.")

        reversals = patterns['trend_reversals'][selected_ticker]

        if not reversals:
            return title, go.Figure().update_layout(title="No trend reversal data available"), html.P(
                "No trend reversal data available for the selected ticker.")

        # Create dataframe for visualization
        reversal_df = pd.DataFrame(reversals)

        # Convert datetime strings to datetime objects if needed
        if 'datetime' in reversal_df.columns and isinstance(reversal_df['datetime'].iloc[0], str):
            reversal_df['datetime'] = pd.to_datetime(reversal_df['datetime'])

        # Calculate time_minutes if not present
        if 'time_minutes' not in reversal_df.columns and 'time' in reversal_df.columns:
            reversal_df['time_minutes'] = reversal_df['time'].apply(time_to_minutes)

        # Sort by time
        reversal_df = reversal_df.sort_values('time_minutes')

        # Create scatter plot for trend reversals
        fig = go.Figure()

        # Create separate traces for different reversal types
        for reversal_type in reversal_df['reversal_type'].unique():
            df_subset = reversal_df[reversal_df['reversal_type'] == reversal_type]

            # Determine symbol based on reversal type
            if 'trough_to_peak' in reversal_type or 'from_trough_to_peak' in reversal_type:
                symbol = 'triangle-up'
                color = 'green'
            elif 'peak_to_trough' in reversal_type or 'from_peak_to_trough' in reversal_type:
                symbol = 'triangle-down'
                color = 'red'
            else:
                symbol = 'circle'
                color = 'gray'

            fig.add_trace(go.Scatter(
                x=df_subset['time_minutes'],
                y=df_subset['price_change_pct'],
                mode='markers',
                marker=dict(
                    size=df_subset['volume_ratio'] * 5,  # Size based on volume ratio
                    symbol=symbol,
                    color=color,
                    opacity=0.8,
                    line=dict(width=1, color='white')
                ),
                text=[
                    f"Time: {row['time']}<br>"
                    f"Price Change: {row['price_change_pct']:.2f}%<br>"
                    f"Reversal Type: {row['reversal_type']}<br>"
                    f"Duration: {row['duration_minutes']:.1f} min<br>"
                    f"Volume Ratio: {row['volume_ratio']:.2f}"
                    for _, row in df_subset.iterrows()
                ],
                hoverinfo='text',
                name=reversal_type
            ))

        # Update layout
        fig.update_layout(
            title=f"Trend Reversals for {selected_ticker}",
            xaxis=dict(
                title="Time of Day",
                tickmode='array',
                tickvals=list(range(0, 24 * 60 + 1, 60)),
                ticktext=[f"{h:02d}:00" for h in range(25)],
                range=[0, 24 * 60]
            ),
            yaxis=dict(
                title="Price Change %"
            ),
            height=600,
            hovermode='closest',
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )

        # Add reference lines for trading sessions
        if 'pattern_summary' in patterns and 'session_times' in patterns['pattern_summary']:
            session_times = patterns['pattern_summary']['session_times']

            # Add marker lines for sessions if available
            sessions = ['pre_market', 'main_session', 'post_market']
            colors = ['blue', 'green', 'purple']

            for session, color in zip(sessions, colors):
                if session in session_times:
                    start_time = session_times[session]['start']
                    end_time = session_times[session]['end']

                    start_minutes = time_to_minutes(start_time)
                    end_minutes = time_to_minutes(end_time)

                    # Handle overnight sessions
                    if end_minutes < start_minutes:
                        end_minutes += 24 * 60

                    # Add vertical lines
                    fig.add_vline(x=start_minutes, line_width=1, line_dash="dash", line_color=color, opacity=0.5)
                    if end_minutes <= 24 * 60:
                        fig.add_vline(x=end_minutes, line_width=1, line_dash="dash", line_color=color, opacity=0.5)

        # Add zero line
        fig.add_hline(y=0, line_width=1, line_dash="solid", line_color="gray")

        # Create detail text for common reversals
        details = []

        # Calculate statistics by reversal type
        reversal_stats = reversal_df.groupby('reversal_type').agg({
            'price_change_pct': ['mean', 'std', 'count'],
            'duration_minutes': ['mean', 'std'],
            'volume_ratio': ['mean', 'max']
        }).reset_index()

        for _, stat in reversal_stats.iterrows():
            reversal_type = stat['reversal_type']
            count = stat[('price_change_pct', 'count')]
            mean_change = stat[('price_change_pct', 'mean')]
            mean_duration = stat[('duration_minutes', 'mean')]
            mean_volume = stat[('volume_ratio', 'mean')]

            details.append(html.P([
                html.Strong(f"{reversal_type}: "),
                f"{count} occurrences, Avg change: {mean_change:.2f}%, ",
                f"Avg duration: {mean_duration:.1f} min, ",
                f"Avg volume ratio: {mean_volume:.2f}"
            ]))

        details = [html.P("Trend reversals show points where price trends change direction.")] + details

        return title, fig, details

    # Default return
    return "Advanced Analysis", go.Figure(), html.P("Select an analysis type and ticker.")


@callback(
    Output("annotation-pattern-selector", "options"),
    Output("annotation-pattern-selector", "value"),
    Input("annotation-ticker-selector", "value"),
    Input("annotation-pattern-type-selector", "value")
)
def update_pattern_selector(selected_ticker, pattern_type):
    if not patterns or pattern_type not in patterns or not selected_ticker:
        return [], None

    pattern_data = patterns[pattern_type]
    if not pattern_data or selected_ticker not in pattern_data:
        return [], None

    if pattern_type == 'recurring_patterns':
        ticker_patterns = pattern_data[selected_ticker]
        options = [{'label': f"{time_str} - {pattern.get('mean_price_change', 0):.2f}%", 'value': time_str}
                   for time_str, pattern in ticker_patterns.items()]

        # Sort by time
        options.sort(key=lambda x: time_to_minutes(x['value']))

        value = options[0]['value'] if options else None
        return options, value

    elif pattern_type == 'temporal_clusters':
        clusters = pattern_data[selected_ticker]
        options = [{'label': f"Cluster {cluster_id} - {cluster.get('mean_time', '00:00')}",
                    'value': cluster.get('mean_time', '00:00')}
                   for cluster_id, cluster in clusters.items()]

        # Sort by time
        options.sort(key=lambda x: time_to_minutes(x['value']))

        value = options[0]['value'] if options else None
        return options, value

    elif pattern_type == 'trend_reversals':
        reversals = pattern_data[selected_ticker]
        # Group by time for simplicity
        times = {}
        for reversal in reversals:
            time_str = reversal.get('time', '00:00')
            if time_str not in times:
                times[time_str] = reversal

        options = [{'label': f"{time_str} - {reversal.get('reversal_type', 'unknown')}", 'value': time_str}
                   for time_str, reversal in times.items()]

        # Sort by time
        options.sort(key=lambda x: time_to_minutes(x['value']))

        value = options[0]['value'] if options else None
        return options, value

    return [], None


@callback(
    Output("annotation-pattern-details", "children"),
    Output("annotation-text", "value"),
    Input("annotation-ticker-selector", "value"),
    Input("annotation-pattern-type-selector", "value"),
    Input("annotation-pattern-selector", "value")
)
def update_annotation_details(selected_ticker, pattern_type, selected_pattern):
    if not patterns or pattern_type not in patterns or not selected_ticker or not selected_pattern:
        return html.P("Select a ticker and pattern to see details."), ""

    pattern_data = patterns[pattern_type]
    if not pattern_data or selected_ticker not in pattern_data:
        return html.P("No pattern data available."), ""

    # Get existing annotation
    annotation = get_pattern_annotation(selected_ticker, pattern_type, selected_pattern)

    if pattern_type == 'recurring_patterns':
        ticker_patterns = pattern_data[selected_ticker]
        if selected_pattern not in ticker_patterns:
            return html.P("Pattern not found."), annotation

        pattern = ticker_patterns[selected_pattern]

        details = [
            html.P([html.Strong("Time: "), selected_pattern]),
            html.P([html.Strong("Session: "), pattern.get('session', 'Unknown')]),
            html.P([html.Strong("Mean Price Change: "), f"{pattern.get('mean_price_change', 0):.2f}%"]),
            html.P([html.Strong("Direction Consistency: "), f"{pattern.get('direction_consistency', 0) * 100:.1f}%"]),
            html.P([html.Strong("Direction: "), pattern.get('consistent_direction', 'neutral')]),
            html.P([html.Strong("Count: "), str(pattern.get('count', 0))]),
            html.P([html.Strong("p-value: "), f"{pattern.get('p_value', 1):.4f}"])
        ]

        return html.Div(details), annotation

    elif pattern_type == 'temporal_clusters':
        clusters = pattern_data[selected_ticker]

        # Find the cluster with matching mean_time
        selected_cluster = None
        selected_cluster_id = None
        for cluster_id, cluster in clusters.items():
            if cluster.get('mean_time', '00:00') == selected_pattern:
                selected_cluster = cluster
                selected_cluster_id = cluster_id
                break

        if not selected_cluster:
            return html.P("Pattern not found."), annotation

        details = [
            html.P([html.Strong("Cluster ID: "), str(selected_cluster_id)]),
            html.P([html.Strong("Mean Time: "), selected_pattern]),
            html.P([html.Strong("Mean Price Impact: "), f"{selected_cluster.get('mean_price_impact', 0):.2f}%"]),
            html.P([html.Strong("Count: "), str(selected_cluster.get('count', 0))]),
            html.P([html.Strong("Time Std Dev: "), f"{selected_cluster.get('std_time_minutes', 0):.1f} min"]),
            html.P([html.Strong("Price Std Dev: "), f"{selected_cluster.get('std_price_impact', 0):.2f}%"]),
            html.P([html.Strong("Statistically Significant: "),
                    "Yes" if selected_cluster.get('is_statistically_significant', False) else "No"])
        ]

        return html.Div(details), annotation

    elif pattern_type == 'trend_reversals':
        reversals = pattern_data[selected_ticker]

        # Find the reversal with matching time
        selected_reversal = None
        for reversal in reversals:
            if reversal.get('time', '00:00') == selected_pattern:
                selected_reversal = reversal
                break

        if not selected_reversal:
            return html.P("Pattern not found."), annotation

        details = [
            html.P([html.Strong("Time: "), selected_pattern]),
            html.P([html.Strong("Reversal Type: "), selected_reversal.get('reversal_type', 'unknown')]),
            html.P([html.Strong("Price Change: "), f"{selected_reversal.get('price_change_pct', 0):.2f}%"]),
            html.P([html.Strong("Duration: "), f"{selected_reversal.get('duration_minutes', 0):.1f} min"]),
            html.P([html.Strong("Volume Ratio: "), f"{selected_reversal.get('volume_ratio', 1):.2f}"])
        ]

        return html.Div(details), annotation

    return html.P("Select a ticker and pattern to see details."), ""


@callback(
    Output("all-annotations-table", "data"),
    Input("save-annotation-button", "n_clicks"),
    Input("delete-annotation-button", "n_clicks"),
    State("annotation-ticker-selector", "value"),
    State("annotation-pattern-type-selector", "value"),
    State("annotation-pattern-selector", "value"),
    State("annotation-text", "value")
)
def update_annotations_table(ticker, pattern_type, pattern_time, annotation_text):
    ctx = dash.callback_context

    if not ctx.triggered:
        # Just load all annotations
        annotations_df = get_all_annotations()
        return annotations_df.to_dict('records')

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if trigger_id == "save-annotation-button" and ticker and pattern_type and pattern_time:
        save_pattern_annotation(ticker, pattern_type, pattern_time, annotation_text)

    elif trigger_id == "delete-annotation-button" and ticker and pattern_type and pattern_time:
        delete_pattern_annotation(ticker, pattern_type, pattern_time)

    # Get updated annotations
    annotations_df = get_all_annotations()
    return annotations_df.to_dict('records')


# Main function to run the app
if __name__ == '__main__':
    # Setup database for annotations
    setup_database()

    # Load pattern data
    patterns = load_pattern_data()

    # Set app layout
    app.layout = create_layout(patterns)

    # Run the app
    app.run_server(debug=True, port=8050)
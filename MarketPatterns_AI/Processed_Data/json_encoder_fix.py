import json
import logging
from typing import Any, Dict, List, Protocol, runtime_checkable

# Only import what's actually used
import pandas as pd

logger = logging.getLogger(__name__)


# Define a protocol for file-like objects that support write
@runtime_checkable
class SupportsWrite(Protocol):
    def write(self, s: str) -> int: ...


class EnhancedJSONEncoder(json.JSONEncoder):
    """
    Enhanced JSON encoder with improved Python 3.13 compatibility for NumPy types.
    """

    def default(self, obj: Any) -> Any:
        # Handle NumPy scalar types
        if hasattr(obj, 'dtype') and hasattr(obj, 'item'):
            # Handle all NumPy scalars via item() method
            try:
                return obj.item()
            except (ValueError, TypeError):
                pass

        # Handle NumPy arrays
        if hasattr(obj, 'tolist') and callable(obj.tolist):
            try:
                return obj.tolist()
            except (TypeError, ValueError) as e:
                logger.warning(f"Error converting NumPy array using tolist(): {e}")

        # Handle date-like objects
        if hasattr(obj, 'isoformat') and callable(obj.isoformat):
            return obj.isoformat()

        # Handle pandas Series and DataFrames
        if isinstance(obj, pd.Series):
            return obj.to_list()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict('records')

        # Handle objects with __dict__ attribute for custom classes
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}

        # Let the base class handle the rest
        return super().default(obj)


def safe_json_dump(data: Any, file_path: str, indent: int = 2) -> bool:
    """
    Safely write data to JSON file with enhanced type handling.

    Args:
        data: The data to serialize to JSON
        file_path: Path to the output file
        indent: Indentation level for pretty-printing

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Special handling for temporal_clusters
        if 'temporal_clusters' in str(file_path):
            processed_data: Dict[str, Dict[str, Dict[str, Any]]] = {}

            for ticker, clusters in data.items():
                processed_data[ticker] = {}
                for cluster_id, cluster in clusters.items():
                    # Convert all values to basic Python types
                    processed_cluster: Dict[str, Any] = {}

                    for k, v in cluster.items():
                        # Handle events lists specially
                        if k == 'events' and isinstance(v, list):
                            processed_events: List[Any] = []

                            for event in v:
                                if isinstance(event, dict):
                                    processed_event: Dict[str, Any] = {}

                                    for ek, ev in event.items():
                                        # Convert NumPy/pandas types to Python native types
                                        if hasattr(ev, 'item') and callable(ev.item):
                                            try:
                                                processed_event[ek] = ev.item()
                                            except (ValueError, TypeError):
                                                processed_event[ek] = str(ev)
                                        elif hasattr(ev, 'isoformat') and callable(ev.isoformat):
                                            processed_event[ek] = ev.isoformat()
                                        else:
                                            processed_event[ek] = ev

                                    processed_events.append(processed_event)
                                else:
                                    processed_events.append(str(event))

                            processed_cluster[k] = processed_events
                        # Handle all other values
                        elif hasattr(v, 'item') and callable(v.item):
                            try:
                                processed_cluster[k] = v.item()
                            except (ValueError, TypeError):
                                processed_cluster[k] = str(v)
                        elif hasattr(v, 'tolist') and callable(v.tolist):
                            try:
                                processed_cluster[k] = v.tolist()
                            except (ValueError, TypeError):
                                processed_cluster[k] = str(v)
                        else:
                            processed_cluster[k] = v

                    # Convert cluster_id to string for dictionary key
                    str_cluster_id = str(cluster_id)
                    processed_data[ticker][str_cluster_id] = processed_cluster

            data = processed_data

        # Write to file with enhanced encoder
        with open(file_path, 'w') as file_obj:
            # Using a different variable name to avoid confusion
            # Type checking hint to handle SupportsWrite expectation
            json.dump(data, file_obj, indent=indent, cls=EnhancedJSONEncoder)  # type: ignore

        return True
    except (IOError, OSError) as e:
        logger.error(f"File I/O error writing JSON to {file_path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error writing JSON to {file_path}: {e}")
        return False
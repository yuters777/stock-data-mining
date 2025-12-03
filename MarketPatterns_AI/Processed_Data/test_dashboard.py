import unittest
import pandas as pd
import json
import os
import sqlite3
from Interactive_Pattern_Analysis_Dashboard import (
    load_pattern_data, time_to_minutes, minutes_to_time,
    get_pattern_annotation, save_pattern_annotation, delete_pattern_annotation,
    setup_database
)


class TestDashboardFunctions(unittest.TestCase):
    def setUp(self):
        """Set up test environment with sample data."""
        # Create test data
        self.test_patterns = {
            'recurring_patterns': {
                'AAPL': {
                    '09:30': {
                        'mean_price_change': 0.5,
                        'direction_consistency': 0.8,
                        'consistent_direction': 'positive',
                        'count': 15,
                        'p_value': 0.02,
                        'session': 'main_session'
                    }
                }
            }
        }

        # Create test directory
        os.makedirs('test_data', exist_ok=True)

        # Save test data to a temporary file
        with open('test_data/recurring_patterns.json', 'w') as f:
            json.dump(self.test_patterns['recurring_patterns'], f)

        # Set up test database
        self.test_db = 'test_annotations.db'
        conn = sqlite3.connect(self.test_db)
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

    def tearDown(self):
        """Clean up test environment."""
        # Remove test file
        if os.path.exists('test_data/recurring_patterns.json'):
            os.remove('test_data/recurring_patterns.json')

        # Remove test directory
        if os.path.exists('test_data'):
            os.rmdir('test_data')

        # Remove test database
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_time_conversion(self):
        """Test time string to minutes conversion and back."""
        minutes = time_to_minutes('14:30')
        self.assertEqual(minutes, 14 * 60 + 30)

        time_str = minutes_to_time(870)
        self.assertEqual(time_str, '14:30')

    def test_pattern_data_loading(self):
        """Test pattern data loading function."""
        patterns = load_pattern_data('test_data')
        self.assertIn('recurring_patterns', patterns)
        self.assertIn('AAPL', patterns['recurring_patterns'])
        self.assertIn('09:30', patterns['recurring_patterns']['AAPL'])

    def test_database_operations(self):
        """Test database CRUD operations for annotations."""
        # Test data
        ticker = 'AAPL'
        pattern_type = 'recurring_patterns'
        pattern_time = '09:30'
        explanation = 'Test annotation'

        # Original implementation uses global DB file, so we need to patch it
        import types
        from unittest.mock import patch

        # Test save and get
        with patch('sqlite3.connect', return_value=sqlite3.connect(self.test_db)):
            # Save annotation
            result = save_pattern_annotation(ticker, pattern_type, pattern_time, explanation)
            self.assertTrue(result)

            # Get annotation
            retrieved = get_pattern_annotation(ticker, pattern_type, pattern_time)
            self.assertEqual(retrieved, explanation)

            # Delete annotation
            delete_result = delete_pattern_annotation(ticker, pattern_type, pattern_time)
            self.assertTrue(delete_result)

            # Verify deletion
            after_delete = get_pattern_annotation(ticker, pattern_type, pattern_time)
            self.assertEqual(after_delete, "")


if __name__ == '__main__':
    unittest.main()
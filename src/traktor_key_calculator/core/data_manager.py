"""
Data management for the Traktor Key Calculator
"""
import os
import pandas as pd
from traktor_key_calculator.config import COLOR_MAPPING_CATEGORY, DEFAULT_LIBRARY_CSV

class DataManager:
    """Class to handle loading and manipulating track data"""
    
    def __init__(self, status_callback=None):
        """Initialize the data manager"""
        self.table = None
        self.status_callback = status_callback
        
    def load_default_data(self):
        """Load the default dataset"""
        try:
            default_path = DEFAULT_LIBRARY_CSV

            if os.path.exists(default_path):
                df = pd.read_csv(default_path)
                if self.status_callback:
                    self.status_callback(f"Loaded {len(df)} tracks from music_test.csv")
                self.table = df
                return df
            else:
                # For testing, create a sample dataframe if file doesn't exist
                if self.status_callback:
                    self.status_callback("CSV file not found. Using sample data.")

                self.table = pd.DataFrame()
                return self.table
        except Exception as e:
            if self.status_callback:
                self.status_callback(f"Error loading data: {str(e)}")
            return pd.DataFrame()
    
    def load_csv(self, file_path):
        """Load data from a specific CSV file"""
        try:
            df = pd.read_csv(file_path)
            if self.status_callback:
                self.status_callback(f"Loaded {len(df)} tracks from {os.path.basename(file_path)}")
            self.table = df
            return df
        except Exception as e:
            if self.status_callback:
                self.status_callback(f"Error loading file: {str(e)}")
            return None
    
    def get_data(self):
        """Return the current dataframe"""
        if self.table is None:
            return self.load_default_data()
        return self.table
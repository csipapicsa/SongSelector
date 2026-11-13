"""
Data management for the SongSelector
"""
import os

import pandas as pd


class DataManager:
    """Class to handle loading and manipulating track data"""
    
    def __init__(self, status_callback=None):
        """Initialize the data manager"""
        self.table = None
        self.status_callback = status_callback
        
    def load_default_data(self):
        """The library a fresh install starts with: empty. Tracks come in by import (drag and drop,
        Add files / folder, Traktor and Rekordbox playlists); they are kept in library.sqlite."""
        self.table = pd.DataFrame()
        return self.table
    
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
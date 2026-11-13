"""
Music-related calculations for the SongSelector
"""
import math

from songselector.config import CAMELOT_KEY_TO_OPEN_KEY
from songselector.core.key_tables import key_list, musical_key_to_harmonic_key


class KeyCalculator:
    """Class for handling key and BPM calculations"""
    
    def __init__(self):
        self.key_list = key_list
        self.musical_key_to_harmonic_key = musical_key_to_harmonic_key
    
    def calculate_semitone_shift(self, original_bpm, target_bpm):
        """
        Calculate the number of semitones to shift when changing BPM
        
        Args:
            original_bpm (float): The original track BPM
            target_bpm (float): The target BPM
            
        Returns:
            int: Number of semitones to shift (positive or negative)
        """
        if original_bpm <= 0 or target_bpm <= 0:
            return 0
            
        ratio = target_bpm / original_bpm
        semitone_shift = 12 * math.log2(ratio)
        return round(semitone_shift)
    
    def key_shifter(self, original_key, semitone_shift):
        """
        Shift a musical key by a number of semitones
        
        Args:
            original_key (str): The original musical key (e.g., "C", "F#")
            semitone_shift (int): Number of semitones to shift (positive or negative)
            
        Returns:
            str: The new musical key
        """
        if original_key not in self.key_list:
            return original_key
            
        # Find the index of the original key
        key_index = self.key_list.index(original_key)
        
        # Calculate the new index (wrapping around if necessary)
        new_index = (key_index + semitone_shift) % len(self.key_list)
        
        # Return the new key
        return self.key_list[new_index]
    
    def get_harmonic_key(self, musical_key, scale):
        """
        Get harmonic key notation from musical key and scale
        
        Args:
            musical_key (str): The musical key (e.g., "C", "F#")
            scale (str): The scale ("major" or "minor")
            
        Returns:
            str: The harmonic key notation
        """
        key_with_scale = f"{musical_key}{'m' if scale.lower() == 'minor' else ''}"
        return self.musical_key_to_harmonic_key.get(key_with_scale, "Unknown")

    def camelot_to_open_key(self, camelot_key):
        """
        Convert Camelot key to Open Key notation using direct mapping
        """
        
        camelot_key = camelot_key.lower()

        
        return CAMELOT_KEY_TO_OPEN_KEY.get(camelot_key, "Unknown")
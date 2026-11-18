import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))                                                # src/ash_e_perception
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "ash_e_core"))   # src/ash_e_core
sys.path.insert(0, HERE)

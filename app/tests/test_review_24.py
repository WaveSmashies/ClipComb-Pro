# SPDX-License-Identifier: GPL-3.0-or-later
"""Reference display scaling, span snapping and current palette defaults."""
import sys,unittest,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_ui_scale import monitor_scale
from review_theme import DEFAULT_PALETTE,PRESETS
from review_theme_files import light_palette
from review_buttons import HELP
from review_core import Settings
from review_bindings import action_for
from mpv_native import Mpv

class Preview24Tests(unittest.TestCase):
    def test_resolution_and_portrait_reference(self):
        for bounds,expected in (((0,0,2560,1440),1),((0,0,3840,2160),1.5),((0,0,1920,1080),.75),((-1440,0,0,2560),1)):
            self.assertEqual(monitor_scale(bounds),expected)
    def test_meter_default_is_green_in_every_mode(self):
        self.assertEqual(DEFAULT_PALETTE['level_meter'],'#13ff0d')
        for colors in PRESETS.values():
            self.assertEqual(colors['level_meter'],'#13ff0d');self.assertEqual(light_palette(colors)['level_meter'],'#13ff0d')
    def test_waveform_help_uses_clip(self):
        self.assertNotIn('recording',HELP['regenerate waveform'].lower())
    def test_clear_moments_default(self):
        self.assertEqual(action_for(Settings().data,'Alt+X'),'clear_moments')
    def test_meter_read_is_bounded_while_decoder_is_busy(self):
        engine=object.__new__(Mpv);engine.handle=1;engine.async_values={};engine.async_pending={};calls=[]
        engine.get_property_async=lambda *args:calls.append(args) or 0
        for _ in range(100):self.assertIsNone(engine.request_property('af-metadata/level_meter'))
        self.assertEqual(len(calls),1)
        engine.async_values['af-metadata/level_meter']=({'peak':'value'},time.monotonic())
        self.assertEqual(engine.request_property('af-metadata/level_meter'),{'peak':'value'})

if __name__=='__main__':unittest.main()

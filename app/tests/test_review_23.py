# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for metadata-only metering, star names and reminder choices."""
import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings
from review_marker_colors import PRESETS,color_name
from review_level_meter import peak,LevelMeter
from review_tutorial import should_start

class Preview23Tests(unittest.TestCase):
    def test_native_custom_and_final_cut_color_names(self):
        for name in ('DaVinci Resolve','Premiere Pro','Kdenlive'):
            colors=PRESETS[name];cfg=dict(palette=name)
            self.assertEqual(color_name(0,colors,cfg),'blue')
            changed=list(colors);changed[0]='#123456'
            cfg=dict(palette='Custom',base_palette=name,custom_colors=','.join(changed))
            self.assertEqual(color_name(0,changed,cfg),'')
            self.assertTrue(color_name(2,changed,cfg))
        self.assertEqual(color_name(0,PRESETS['Final Cut Pro'],dict(palette='Final Cut Pro')),'')

    def test_meter_db_volume_and_no_audio(self):
        metadata={'lavfi.astats.Overall.Peak_level':'-20'}
        self.assertAlmostEqual(peak(metadata),.1)
        self.assertAlmostEqual(peak(metadata,50),.0125)
        for data in (None,{}, {'lavfi.astats.Overall.Peak_level':'-inf'}, {'lavfi.astats.Overall.Peak_level':'broken'}):self.assertEqual(peak(data),0)

    def test_new_meter_shortcut_preserves_existing_assignment(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Settings(Path(folder));s.data['shortcuts']['marker']='M';del s.data['shortcuts']['volume_meter'];s.save()
            loaded=Settings(Path(folder));self.assertEqual(loaded.data['shortcuts']['volume_meter'],'');self.assertEqual(loaded.data['shortcuts']['marker'],'M')

    def test_reminder_requires_explicit_dont_show(self):
        cfg=Settings().data['tutorial']
        cfg.update(completed='yes',skipped='yes',first_run_seen='yes')
        self.assertTrue(should_start(cfg));cfg['dont_show']='yes';self.assertFalse(should_start(cfg))

    def test_light_intro_has_only_intro_frames(self):
        root=Path(__file__).resolve().parents[1]/'assets/animation'
        for mode in ('dark','light'):
            info=json.loads((root/f'{mode}-intro.json').read_text())
            self.assertEqual(len(info['durations']),31)
            self.assertLess(sum(info['durations']),1200)

if __name__=='__main__':unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression coverage for queue ordering and shortcut migration."""
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_core import Settings,DEFAULT_KEYS
from review_queue import filtered_clips


class QueueFilters(unittest.TestCase):
    def test_categories_keep_color_slots_and_earliest_bookmark(self):
        clips=[dict(id=str(i),path=f'Unused/{i}.mp4',decision='Unused') for i in range(5)]
        clips[0]['star']=dict(color_slot=4)
        clips[1]['star']=dict(color_slot=0)
        clips[2]['markers']=[dict(id='late',time=8,color_slot=0),dict(id='early',time=1,color_slot=6)]
        clips[3]['markers']=[dict(id='other',time=2,color_slot=1)]
        clips[4]['ranges']=[dict(start=0,end=1,enabled=True)]
        self.assertEqual([c['id'] for c in filtered_clips(clips,'Stars')],['1','0'])
        self.assertEqual([c['id'] for c in filtered_clips(clips,'Bookmarks')],['3','2'])
        self.assertEqual(filtered_clips(clips,'Marks'),[clips[4]])
        self.assertEqual(filtered_clips(clips,'Marked'),[clips[4]])
        self.assertEqual(filtered_clips(clips,'Stars','0.MP4'),[clips[0]])

    def test_new_keys_preserve_an_existing_custom_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(folder)
            settings.data['shortcuts']['play']=DEFAULT_KEYS['star']
            settings.data['shortcuts'].pop('star')
            settings.save()
            migrated=Settings(folder)
            self.assertEqual(migrated.data['shortcuts']['star'],'')
            self.assertEqual(migrated.data['shortcuts']['play'],DEFAULT_KEYS['star'])
            self.assertEqual(migrated.data['shortcuts']['review_page'],'R')
            self.assertEqual(migrated.data['shortcuts']['compare_page'],'C')


if __name__=='__main__':unittest.main()

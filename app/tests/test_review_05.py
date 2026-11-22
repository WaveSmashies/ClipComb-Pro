# SPDX-License-Identifier: GPL-3.0-or-later
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_queue import managed
from review_thumbnails import Thumbnails,delete_thumbnails
from review_icons import asset_folder

class Review05Tests(unittest.TestCase):
    def test_windows_thumbnail_is_not_copied_to_private_disk_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            service=Thumbnails(Path(folder)/'Generated Thumbnails')
            try:
                with patch('review_thumbnails.windows_thumbnail',return_value=Image.new('RGB',(320,180))):
                    service.wanted={'a'*32};service.request('a'*32,Path(folder)/'clip.mp4',None)
                    key,picture=service.results.get(timeout=3)
                self.assertEqual(key,'a'*32);self.assertEqual(picture.size,(320,180))
                self.assertFalse(service.folder.exists())
            finally:service.close()
    def test_cache_cleanup_preserves_foreign_files_and_subfolders(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'Generated Thumbnails';cache.mkdir()
            for name in ('a'*32+'.jpg','b'*32+'.writing','keep.jpg','not-a-cache.txt'):(cache/name).write_bytes(b'test')
            (cache/'foreign folder').mkdir();(cache/'foreign folder/keep.jpg').write_bytes(b'test')
            delete_thumbnails(folder)
            self.assertEqual({p.name for p in cache.iterdir()},{'keep.jpg','not-a-cache.txt','foreign folder'})
    def test_removed_annotations_clear_review_badge(self):
        clip={'decision':'Unused','reviewed':True,'ranges':[],'markers':[],'trim_ranges':[]}
        self.assertFalse(managed(clip))
        for field in ('ranges','markers','trim_ranges'):
            clip[field]=[{'id':'an edit'}];self.assertTrue(managed(clip));clip[field]=[]
            self.assertFalse(managed(clip))
        clip['decision']='Used';self.assertTrue(managed(clip))
    def test_animation_atlases_cover_every_timed_frame(self):
        folder=asset_folder()/'animation'
        for mode in ('dark','light'):
            for action in ('intro','outro'):
                timing=json.loads((folder/f'{mode}-{action}.json').read_text())
                self.assertTrue(all(0<ms<=1000 for ms in timing['durations']))
                with Image.open(folder/f'{mode}-{action}.png') as image:
                    self.assertEqual(image.width,timing['columns']*timing['size'])
                    self.assertGreaterEqual(image.height//timing['size']*timing['columns'],len(timing['durations']))

if __name__=='__main__':unittest.main()

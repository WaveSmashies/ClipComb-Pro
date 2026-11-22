# SPDX-License-Identifier: GPL-3.0-or-later
"""Interchange timing, channel separation and input validation."""
import copy,json,tempfile,unittest,sys
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).parents[1]))
from review_export import rate,frame,validate


class ExportTests(unittest.TestCase):
    def test_fractional_rates_do_not_drift(self):
        self.assertEqual(rate(29.97),Fraction(30000,1001))
        self.assertEqual(rate(59.94005994005994),Fraction(60000,1001))
        self.assertEqual(frame(3600,'30000/1001'),107892)
        self.assertEqual(frame(Fraction(180)/60,30),90)

    def test_validation_excludes_disabled_deleted_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.mp4';path.write_bytes(b'fixture')
            clip={'path':str(path),'media':{'duration':20,'fps':30,'audio':[]},'ranges':[
                {'start':8,'end':9},{'start':1,'end':2},{'start':3,'end':4,'enabled':False}]}
            payload={'schema':1,'time_unit':'source_seconds','clips':[dict(clip,category='Deleted'),clip]}
            selected=validate(payload)
            self.assertEqual(len(selected),1);self.assertEqual([r['start'] for r in selected[0]['ranges']],[8,1])
            self.assertEqual(payload['clips'][1]['ranges'][0]['start'],8)
            payload['clips'][1]['ranges'][0]['end']=float('nan')
            with self.assertRaises(ValueError):validate(payload)

    def test_subframe_empty_and_missing_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'a.mp4';p.touch()
            data={'schema':1,'time_unit':'source_seconds','clips':[{'path':str(p),'media':{'duration':10,'fps':30},'ranges':[{'start':1,'end':1.001}]}]}
            with self.assertRaises(ValueError):validate(data)
            data['clips'][0]['ranges']=[{'start':1,'end':3}];p.unlink()
            with self.assertRaises(ValueError):validate(data)


if __name__=='__main__':unittest.main()

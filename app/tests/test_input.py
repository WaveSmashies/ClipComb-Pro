# SPDX-License-Identifier: GPL-3.0-or-later
"""Thread-local native side-button bridge: data decoding, modifiers and cleanup."""
import ctypes as c
from ctypes import wintypes as w
import os
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from review_input import ExtraMouseButtons, MouseHookPoint, MouseHookData


@unittest.skipUnless(os.name=='nt','Windows input bridge')
class MouseInputTests(unittest.TestCase):
    def test_middle_button_uses_basic_mouse_data(self):
        bridge = ExtraMouseButtons(lambda button: button == 2)
        self.addCleanup(bridge.close)
        data = MouseHookPoint(w.POINT(120, 340), None, 0, 0)
        self.assertEqual(c.sizeof(data), MouseHookData.mouse_data.offset)
        for message, down in ((0x207, True), (0x208, False), (0x209, True)):
            self.assertEqual(bridge.callback(0, message, c.addressof(data)), 1)
            button, pressed, _, x, y = bridge.events.get_nowait()
            self.assertEqual((button, pressed, x, y), (2, down, 120, 340))

    def test_side_buttons_use_thread_local_queue(self):
        bridge=ExtraMouseButtons(lambda button:True)
        self.addCleanup(bridge.close)
        self.assertTrue(bridge.handle)
        self.assertEqual(c.sizeof(MouseHookData),40)
        for native,button in ((1,4),(2,5)):
            for message,down in ((0x20B,True),(0x20C,False)):
                data=MouseHookData(w.POINT(120,340),None,0,0,native<<16)
                self.assertEqual(bridge.callback(0,message,c.addressof(data)),1)
                event=bridge.events.get_nowait()
                self.assertEqual((event[0],event[1],event[3],event[4]),(button,down,120,340))
        bridge.close()
        self.assertIsNone(bridge.handle)


if __name__=='__main__':
    unittest.main()

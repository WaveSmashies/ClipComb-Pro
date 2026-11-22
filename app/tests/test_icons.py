# SPDX-License-Identifier: GPL-3.0-or-later
"""Original artwork reaches source packages and every standard window."""
from pathlib import Path
import sys
import tkinter as tk
import unittest
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_icons import install_app_icons, asset_folder
from review_theme import dialog


class IconTests(unittest.TestCase):
    def test_supplied_icon_has_small_and_high_dpi_images(self):
        with Image.open(asset_folder() / 'logo.ico') as icon:
            self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows app icons')
    def test_root_and_popup_use_the_logo_without_reloading(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        install_app_icons(root)
        images = root.replaysift_icons
        self.assertEqual(len(images), 7)
        install_app_icons(root)
        self.assertIs(root.replaysift_icons, images)
        window = dialog(root, 'Icon test')
        window.update_idletasks()
        self.assertEqual(root.tk.call('image', 'type', str(images[2])), 'photo')
        self.assertEqual((images[2].width(), images[2].height()), (32, 32))
        window.destroy()


if __name__ == '__main__':
    unittest.main()

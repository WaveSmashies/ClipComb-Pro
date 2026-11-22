# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare small runtime atlases from the author's supplied GIFs and stills."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageSequence

def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=root/'artwork/clipcomb-source/animation')
    parser.add_argument('--output',type=Path,default=root/'assets/animation')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    with Image.open(args.source/'Blank.png') as picture:picture.convert('RGBA').resize((96,96),Image.Resampling.LANCZOS).save(args.output/'blank.png')
    for mode,suffix in [('dark',''),('light',' Light')]:
        for action in ('Intro','Outro'):
            with Image.open(args.source/(action+suffix+'.gif')) as animation:
                frames=[];durations=[]
                for frame in ImageSequence.Iterator(animation):
                    frames.append(frame.convert('RGBA').resize((96,96),Image.Resampling.LANCZOS))
                    durations.append(max(10,frame.info.get('duration',100)))
            # The supplied Light intro GIF exports a complete 132-frame cycle,
            # including hold/outro. The player supplies those phases separately.
            # Preserve the original artwork and normalize only this runtime atlas.
            if mode=='light' and action=='Intro' and len(frames)==132:frames,durations=frames[:31],durations[:31]
            atlas=Image.new('RGBA',(96*16,96*((len(frames)+15)//16)))
            for i,frame in enumerate(frames):atlas.paste(frame,((i%16)*96,(i//16)*96))
            name=mode+'-'+action.lower();atlas.save(args.output/(name+'.png'))
            (args.output/(name+'.json')).write_text(json.dumps({'size':96,'columns':16,'durations':durations}),encoding='utf-8')
        with Image.open(args.source/('Hold'+suffix+'.png')) as picture:
            picture.convert('RGBA').resize((96,96),Image.Resampling.LANCZOS).save(args.output/(mode+'-hold.png'))

if __name__=='__main__':main()

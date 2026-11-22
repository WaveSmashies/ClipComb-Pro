# SPDX-License-Identifier: GPL-3.0-or-later
"""Disk checkpoints for completed packet indexes and overlap comparisons."""
import hashlib,json,sqlite3,zlib
from dataclasses import asdict
from pathlib import Path

class ScanCache:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path);self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS checkpoints (kind TEXT, key TEXT, value BLOB, PRIMARY KEY(kind,key))')
        self.hits=0
    def key(self,values):return hashlib.sha256(json.dumps([1,values],sort_keys=True).encode()).hexdigest()
    def get(self,kind,values):
        row=self.db.execute('SELECT value FROM checkpoints WHERE kind=? AND key=?',(kind,self.key(values))).fetchone()
        if not row:return None
        try:value=json.loads(zlib.decompress(row[0]));self.hits+=1;return value
        except (ValueError,zlib.error):return None
    def put(self,kind,values,data):
        value=zlib.compress(json.dumps(data,separators=(',',':')).encode(),3)
        self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?)',(kind,self.key(values),value));self.db.commit()
    def media(self,clip):
        data=self.get('media',clip.file_id)
        if data is None:return None
        from review_overlap_audit import Media,Track
        tracks=[]
        for record in data['tracks']:
            record['signature']=tuple(record['signature']);record['side_data']={int(k):v for k,v in record['side_data'].items()}
            tracks.append(Track(**record))
        return Media(tracks,data['duration'],data['start'],data['video'])
    def save_media(self,clip,media):self.put('media',clip.file_id,asdict(media))
    def pair(self,key):
        data=self.get('pair',key)
        if data is None:return None
        from review_overlap_audit import Coverage
        return (Coverage(**data[0]) if data[0] else None,data[1],data[2])
    def save_pair(self,key,result):self.put('pair',key,[asdict(result[0]) if result[0] else None,result[1],result[2]])
    def close(self):self.db.close()

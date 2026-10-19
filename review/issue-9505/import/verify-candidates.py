from pathlib import Path
import hashlib
import json
import os
import posixpath
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / 'study'
freeze = json.loads((STUDY / 'freezes/all-v1.json').read_text())
BASE = freeze['config']['base_commit']

def git(*args, env=None):
    return subprocess.check_output(['git', *args],env=env)

def blobs(tree, names):
    data = subprocess.run(['git','cat-file','--batch'], input=('\n'.join(tree+':'+name for name in names)+'\n').encode(), stdout=subprocess.PIPE, check=True).stdout
    offset=0; result={}
    for name in names:
        end=data.index(b'\n',offset); header=data[offset:end].split()
        assert len(header)==3 and header[1]==b'blob', (name,header)
        size=int(header[2]); result[name]=data[end+1:end+1+size]; offset=end+size+2
    assert offset==len(data)
    return result

report={}
with tempfile.TemporaryDirectory(prefix='lance-9505-index-') as temp:
    for label in ['U','B','P','D','CTX','DB','DP']:
        env=dict(os.environ,GIT_INDEX_FILE=str(Path(temp)/label))
        git('read-tree',BASE,env=env)
        if label!='U':
            patch=STUDY/'ports'/label/'implementation.patch'
            git('apply','--cached','--binary','--whitespace=nowarn',str(patch),env=env)
        tree=git('write-tree',env=env).decode().strip()
        modes={}
        for entry in git('ls-tree','-r','-z',tree).split(b'\0'):
            if entry:
                info,name=entry.split(b'\t',1); modes[name.decode()]=info.split()[0].decode()
        expected=freeze['identities'][label]['tree']['source_hashes']
        content=blobs(tree,list(expected))
        symlinks=[]
        for name,sha in expected.items():
            value=content[name]
            if modes[name]=='120000':
                target=posixpath.normpath(posixpath.join(posixpath.dirname(name),value.decode()))
                assert not target.startswith('../') and not target.startswith('/'),target
                value=blobs(tree,[target])[target]; symlinks.append(name)
            assert hashlib.sha256(value).hexdigest()==sha,(label,name)
        changed=[]
        if label!='U':
            changed=git('diff','--cached','--name-only','--diff-filter=ACMRT',BASE,env=env).decode().splitlines()
            source=STUDY/'ports'/label/'source'
            actual={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()}
            assert set(changed)==actual,(label,sorted(set(changed)-actual),sorted(actual-set(changed)))
            for name in changed:
                assert (source/name).read_bytes()==blobs(tree,[name])[name],(label,'snapshot',name)
        report[label]={'base_commit':BASE,'reconstructed_tree':tree,'frozen_source_hashes_verified':len(expected),'changed_source_files':changed,'source_symlinks_verified':symlinks,'patch_applies_to_common_base':True}
print(json.dumps(report,indent=2))

from pathlib import Path
import hashlib
import json
import os
import posixpath
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent.parent
STUDY=ROOT/'study'
freeze=json.loads((STUDY/'freeze-v1.json').read_text())
def git(*args,env=None):return subprocess.check_output(['git',*args],env=env)
def blobs(tree,names):
    data=subprocess.run(['git','cat-file','--batch'],input=('\n'.join(tree+':'+n for n in names)+'\n').encode(),stdout=subprocess.PIPE,check=True).stdout
    result={};pos=0
    for name in names:
        end=data.index(b'\n',pos);h=data[pos:end].split();assert len(h)==3 and h[1]==b'blob',(name,h)
        size=int(h[2]);result[name]=data[end+1:end+1+size];pos=end+size+2
    assert pos==len(data)
    return result
with tempfile.TemporaryDirectory(prefix='lance-9505-probe-index-') as tmp:
    env=dict(os.environ,GIT_INDEX_FILE=str(Path(tmp)/'index'))
    git('read-tree',freeze['base_commit'],env=env)
    git('apply','--cached','--binary','--whitespace=nowarn',str(STUDY/'full-reconstruction.patch'),env=env)
    tree=git('write-tree',env=env).decode().strip()
    modes={}
    for entry in git('ls-tree','-r','-z',tree).split(b'\0'):
        if entry:
            info,name=entry.split(b'\t',1);modes[name.decode()]=info.split()[0].decode()
    expected=freeze['full_tree_identity']['source_hashes'];content=blobs(tree,list(expected))
    for name,sha in expected.items():
        value=content[name]
        if modes[name]=='120000':
            target=posixpath.normpath(posixpath.join(posixpath.dirname(name),value.decode()))
            assert not target.startswith(('../','/')),target
            value=blobs(tree,[target])[target]
        assert hashlib.sha256(value).hexdigest()==sha,name
    changed=git('diff','--cached','--name-only','--diff-filter=ACMRT',freeze['base_commit'],env=env).decode().splitlines()
    snapshot=STUDY/'snapshot';actual={str(p.relative_to(snapshot)) for p in snapshot.rglob('*') if p.is_file()}
    assert actual==set(changed),(actual-set(changed),set(changed)-actual)
    for name in changed:assert (snapshot/name).read_bytes()==blobs(tree,[name])[name],name
    result={'status':'passed','base_commit':freeze['base_commit'],'reconstructed_tree':tree,'source_hashes_verified':len(expected),'snapshot_files_verified':len(changed),'changed_files':changed,'patch':'full-reconstruction.patch','scope':'Temporary Git index only. No source edits, builds, workloads, or dataset validation.'}
print(json.dumps(result,indent=2))

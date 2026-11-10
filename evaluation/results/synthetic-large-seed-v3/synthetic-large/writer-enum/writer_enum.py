import importlib.util, json, re, subprocess, sys
from pathlib import Path
ROOT=Path('/home/minix/codes/heimdall-rs')
def L(n,p):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
b=L('rb',ROOT/'evaluation/scripts/run_behavior.py')
CALLER='0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'
REF, CAND='0x1000000000000000000000000000000000001001','0x2000000000000000000000000000000000002002'
SETTER='Unresolved_c4590d3f'
REFSIGS={'initialize':'initialize(address)','setLimits':'setLimits(uint256,uint256)','setFee':'setFee(uint256)','mint':'mint(address,uint256)','getStats':'getStats(address)','deposit':'deposit(uint256)'}
SETUP=['initialize(address):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:send','setLimits(uint256,uint256):1:1000000:send','setFee(uint256):100:send','mint(address,uint256):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:1000:send']
CHECKS=['getStats(address):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:','deposit(uint256):100:send','deposit(uint256):1000001:send']
def cand_sigs(src):
    d={}
    for m in re.finditer(r'function\s+([A-Za-z_]\w*)\s*\(([^)]*)\)',src):
        n,pa=m.group(1),m.group(2); t=','.join(x.strip().split()[0] for x in pa.split(',') if x.strip())
        d[n]=f'{n}({t})'
    return d
def sig_for(cands,name):
    if cands is None: return REFSIGS[name]
    want=REFSIGS[name]; sel=subprocess.run(['cast','sig',want],capture_output=True,text=True).stdout.strip().lower()
    for n,sig in cands.items():
        tok=n.split('_')[-1]
        if re.fullmatch(r'[0-9a-fA-F]{8}',tok or '') and ('0x'+tok.lower())==sel: return sig
    return want
CANDSIGS=None
def calldata_of(sig_spec, refside):
    sig,_,rest=sig_for(None, sig_spec.split('(')[0]) if False else (None,None,None)
def cd(spec, refside):
    spec=spec[:-5] if spec.endswith(':send') else spec
    name,_,args=spec.partition(':')
    args=[a for a in args.split(':') if a]
    base=name.split('(')[0]
    sig=sig_for(None,base) if refside else sig_for(CANDSIGS,base)
    out=subprocess.run(['cast','calldata',sig,*args],capture_output=True,text=True,timeout=30)
    if out.returncode!=0 and args:
        # candidate selector + full reference arg encoding: the surplus
        # words are exactly the msg.data suffix under test
        sel=subprocess.run(['cast','sig',sig],capture_output=True,text=True,timeout=30).stdout.strip()
        words=''.join('%064x'%int(a,0) if not a.startswith('0x') else a[2:].rjust(64,'0') for a in args)
        return sel+words
    assert out.returncode==0,(sig,args,out.stderr)
    return out.stdout.strip()
def seq(rpc,addr,refside,steps):
    snap=rpc.call('evm_snapshot')
    try:
        out=[]
        for spec in steps:
            r=b.call_step(rpc,addr,cd(spec,refside),CALLER,0,spec.endswith(':send'))
            out.append((r['ok'],(r['return_data'] or '')[:64],(r['revert_data'] or '')[:64]))
        return out
    finally: rpc.call('evm_revert',[snap])
seed=Path('/tmp/synth-deposit/candidate.sol').read_text()
CANDSIGS=cand_sigs(seed)
i=seed.index(f'function {SETTER}'); j=seed.index('\n    }\n',i)+7
variants={
 'suffix':'function %s(uint256 arg0) public {\n        require(arg0 == 1);\n        store_c = arg0;\n        store_d = uint256(bytes32(msg.data[0x24:0x44]));\n        var_c = arg0;\n        emit Event_d83d5281(arg0);\n    }'%SETTER,
 'plain':seed[i:j],
}
a=b.Anvil()
try:
    rpc=a.rpc
    refhex=Path('evaluation/fixtures/synthetic-large/runtime.hex').read_text().strip()
    if not refhex.startswith('0x'): refhex='0x'+refhex
    rpc.call('anvil_setCode',[REF,refhex])
    ref=seq(rpc,REF,True,SETUP+CHECKS)
    print('ref:',ref)
    ledger=[]
    for name,text in variants.items():
        mut=seed[:i]+text+seed[j:]
        rec=b.compile_candidate(mut,'0.8.30',Path(f'/tmp/we2-{name}'),name)
        e={'name':name,'compiled':bool(rec.get('ok'))}
        if rec.get('ok'):
            rpc.call('anvil_setCode',[CAND,rec['deployed_bytecode']])
            cand=seq(rpc,CAND,False,SETUP+CHECKS)
            e['obs']=cand; e['matches']=cand==ref
            if not e['matches']:
                e['first_diff']=next(k for k,(x,y) in enumerate(zip(cand,ref)) if x!=y)
        else: e['err']=(rec.get('stderr') or '')[-250:]
        ledger.append(e); print(name,e.get('matches'),e.get('obs'))
    Path('/tmp/we2-ledger.json').write_text(json.dumps(ledger,indent=1))
finally: a.stop()

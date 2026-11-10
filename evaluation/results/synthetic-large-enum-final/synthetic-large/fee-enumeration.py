import importlib.util,subprocess,sys
from pathlib import Path
def L(n,p):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
b=L('rb',Path('/home/minix/codes/heimdall-rs/evaluation/scripts/run_behavior.py'))
C='0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'
REF,CAND='0x1000000000000000000000000000000000001001','0x2000000000000000000000000000000000002002'
base=Path('/tmp/full-winner2.sol').read_text()
MARK='    function Unresolved_b6b55f25(uint256 arg0) public {\n        if (store_c > arg0 || arg0 > store_d) { revert CustomError_3261c792(); }\n    }'
def variant(div):
    newbody=('    function Unresolved_b6b55f25(uint256 arg0) public {\n'
             '        if (store_c > arg0 || arg0 > store_d) { revert CustomError_3261c792(); }\n'
             '        uint256 net = arg0 - (arg0 * unresolved_ddca3f43) / %d;\n'
             '        unresolved_70a08231[msg.sender] += net;\n'
             '        var_c += net;\n    }') % div
    return base.replace(MARK,newbody) if MARK in base else None
def cd(sig,args):
    o=subprocess.run(['cast','calldata',sig,*args],capture_output=True,text=True,timeout=30)
    if o.returncode==0: return o.stdout.strip()
    sel=subprocess.run(['cast','sig',sig],capture_output=True,text=True,timeout=30).stdout.strip()
    return sel+''.join('%064x'%int(x,0) if x.isdigit() else x[2:].rjust(64,'0') for x in args)
RSETUP=[('initialize(address)',[C]),('setLimits(uint256,uint256)',['1','1000000']),('setFee(uint256)',['100']),('mint(address,uint256)',[C,'1000'])]
CSETUP=[('Unresolved_c4d66de8(address)',[C]),('Unresolved_c4590d3f(uint256)',['1','1000000']),('Unresolved_69fe0e2d(uint256)',['100']),('Unresolved_40c10f19(address,uint256)',[C,'1000'])]
CSIG={'dep':'Unresolved_b6b55f25(uint256)','bal':'unresolved_70a08231(address)','sup':'Unresolved_18160ddd()','stats':'Unresolved_c23f85d6(address)'}
RSIG={'dep':'deposit(uint256)','bal':'balanceOf(address)','sup':'totalSupply()','stats':'getStats(address)'}
PROBE=[('dep','100'),('dep','7'),('dep','1000001'),('bal',None),('sup',None),('stats',None)]
a=b.Anvil()
try:
    rpc=a.rpc
    refhex=Path('/home/minix/codes/heimdall-rs/evaluation/fixtures/synthetic-large/runtime.hex').read_text().strip()
    if not refhex.startswith('0x'): refhex='0x'+refhex
    def run(addr,setup,S):
        snap=rpc.call('evm_snapshot')
        try:
            for sig,args in setup: b.call_step(rpc,addr,cd(sig,args),C,0,True)
            out=[]
            for kind,args in PROBE:
                send=kind=='dep'
                s2=rpc.call('evm_snapshot') if send else None
                r=b.call_step(rpc,addr,cd(S[kind],args or []),C,0,send)
                out.append((r['ok'],r['return_data'] or '',r['revert_data'] or ''))
                if s2: rpc.call('evm_revert',[s2])
            return out
        finally: rpc.call('evm_revert',[snap])
    rpc.call('anvil_setCode',[REF,refhex])
    R=run(REF,RSETUP,RSIG)
    print('REF:',[(x[0],x[1][:18]) for x in R])
    for div in (10000,1000,100):
        src=variant(div)
        rec=b.compile_candidate(src,'0.8.30',Path('/tmp/e15w%d'%div),'x')
        if not rec.get('ok'): print(div,'compile fail',(rec.get('stderr') or '')[-140:]); continue
        rpc.call('anvil_setCode',[CAND,rec['deployed_bytecode']])
        K=run(CAND,CSETUP,CSIG)
        par=[x==y for x,y in zip(R,K)]
        print('div',div,'parity',par)
        if all(par):
            Path('/tmp/FINAL-winner.sol').write_text(src); print('FINAL WINNER div',div); break
        else:
            for k,(x,y) in enumerate(zip(R,K)):
                if x!=y: print('  diff',k,PROBE[k][0],x[1][:40] or x[2][:20],'|',y[1][:40] or y[2][:20])
finally: a.stop()

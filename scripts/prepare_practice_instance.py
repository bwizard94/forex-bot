"""Stage an isolated practice instance; never start it or submit broker orders."""
from pathlib import Path
import hashlib,json,shutil,subprocess
from pydantic import SecretStr


def prepare(source,destination,settings,account,port=8766):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Refusing to overwrite an instance')
    if settings.oanda_environment!='practice':raise ValueError('Practice only')
    if account==settings.oanda_account_id:raise ValueError('Second instance needs a different account')
    if port==settings.dashboard_port:raise ValueError('Dashboard ports must differ')
    if not account.startswith('101-'):raise ValueError('Expected a practice account identifier')
    files=subprocess.check_output(['git','ls-files','-z'],cwd=source).decode().split('\0')
    destination.mkdir(parents=True,mode=0o700)
    hashes={}
    for name in files:
        if not name:continue
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Invalid source path')
        if rel.parts[0] not in {'src','desk','scripts'} and name not in {'requirements.txt','README.md','README.part1.md','README.part2.md','.env.example'}:continue
        original=source/rel
        if original.is_symlink() or not original.is_file():continue
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original,target);hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    # Copy active strategy parameters, but no unrelated service credentials or MT4 password.
    values={}
    for name,value in settings:
        if isinstance(value,SecretStr):
            values[name]=value.get_secret_value() if name in {'oanda_api_token','twelvedata_api_key','currencyfreaks_api_key','tavily_api_key'} else ''
        elif value is not None:
            values[name]=value.isoformat() if hasattr(value,'isoformat') else value
    values.update(oanda_account_id=account,oanda_environment='practice',
        database_url='sqlite:///./data/forex_bot.db',dashboard_host='127.0.0.1',dashboard_port=port,
        enable_trading=False,mt4_enabled=False,sheets_sync_enabled=False)
    env=destination/'.env'
    with env.open('x') as f:
        env.chmod(0o600)
        for key,value in values.items():
            # Single quoted dotenv scalar: preserve literals without shell interpolation.
            scalar=json.dumps(value) if isinstance(value,(bool,list,dict)) else str(value)
            scalar=scalar.replace('\\','\\\\').replace("'","\\'")
            f.write(key.upper()+"='"+scalar+"'\n")
    (destination/'data').mkdir();(destination/'logs').mkdir()
    manifest={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),
        'source_sha256':hashes,'account_suffix':account[-3:],'dashboard_port':port,
        'state':'staged_not_started','trading_enabled':False,
        'notes':['No execution database or generated journals copied.','Separate module paths isolate desk, data, locks and research.',
        'API access and non-MT4 compatibility must be verified before activation.','No MT4 password is used or stored.']}
    (destination/'INSTANCE.json').write_text(json.dumps(manifest,indent=2))
    return {'directory':str(destination),'port':port,'files':len(hashes),'state':manifest['state']}

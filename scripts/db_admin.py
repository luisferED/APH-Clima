"""Consistent SQLite maintenance; never imports on application startup."""
from contextlib import closing
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile


def inspect(path, complete=False):
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
        if integrity != ['ok']:
            raise RuntimeError(str(integrity))
        cities = db.execute('SELECT city_slug FROM weather_cache ORDER BY city_slug').fetchall()
        forecasts = db.execute('SELECT city_slug, count(*) FROM forecast_days GROUP BY city_slug ORDER BY city_slug').fetchall()
        state = db.execute('SELECT key,value FROM kv_store ORDER BY key').fetchall()
        if complete:
            expected = {'la-paz','santa-cruz','cochabamba','sucre','oruro','potosi','tarija','trinidad','cobija'}
            if {r[0] for r in cities} != expected or forecasts != [(r[0], 4) for r in cities]:
                raise RuntimeError('Se requieren 9 ciudades y 36 pronosticos (4 por ciudad)')
        return {'integrity': integrity, 'cities': len(cities), 'forecasts': sum(r[1] for r in forecasts), 'state': state}


def backup(source, destination, complete=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise RuntimeError('El destino debe ser nuevo; no se sobrescribe')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.aph-backup-', dir=destination.parent)
    os.close(fd)
    temp = Path(name)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(temp)) as dst:
            src.backup(dst)
        result = inspect(temp, complete)
        os.chmod(temp, 0o600)
        # Atomic publication without replacement; temp and destination share a filesystem.
        with temp.open('r+b') as inp:
            os.fsync(inp.fileno())
        os.link(temp, destination)
        return result
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['hash-password','check','backup','import','restore'])
    parser.add_argument('source', nargs='?')
    parser.add_argument('destination', nargs='?')
    args = parser.parse_args()
    if args.command == 'hash-password':
        password = getpass.getpass('Contrasena (minimo 14 caracteres): ')
        if len(password) < 14 or password != getpass.getpass('Repetir: '):
            raise RuntimeError('Contrasena corta o diferente')
        salt = secrets.token_bytes(16)
        print('600000:' + salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex())
    elif args.command == 'check':
        print(json.dumps(inspect(args.source, True), ensure_ascii=False))
    else:
        if args.command in ('import', 'restore') and os.environ.get('APH_OFFLINE_MAINTENANCE') != 'YES':
            raise RuntimeError('Deten el servicio y configura APH_OFFLINE_MAINTENANCE=YES')
        print(json.dumps(backup(args.source, args.destination, args.command in ('import','restore')), ensure_ascii=False))


if __name__ == '__main__':
    main()


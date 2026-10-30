"""Terminal-capable job runner with a durable log and explicit completion result."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from .state import write_json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action')
    parser.add_argument('--log', required=True)
    parser.add_argument('--result', required=True)
    parser.add_argument('--plan')
    args = parser.parse_args()
    command = [sys.executable, '-u', '-m', 'spark_link.jobs', args.action]
    if args.plan: command += ['--plan', args.plan]
    code = 1
    try:
        with Path(args.log).open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
    except BaseException as exc:
        with Path(args.log).open('a') as log:
            log.write('\nОшибка запуска: ' + str(exc) + '\n')
    finally:
        write_json(args.result, {'returncode': code})
    return code

if __name__ == '__main__':
    raise SystemExit(main())

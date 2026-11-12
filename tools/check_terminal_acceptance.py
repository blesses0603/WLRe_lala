#!/usr/bin/env python3
"""Linux/POSIX PTY checks; run after Release build with dotnet on PATH. Fake data only."""
import errno
import os
import pathlib
import pty
import select
import subprocess
import sys
import termios
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMAND = ['dotnet', str(ROOT / 'dotnet/Lala.Cloud.Acceptance/bin/Release/net10.0/Lala.Cloud.Acceptance.dll'), '--terminal-self-test']


def scenario(name, steps, expected, code, forbidden=()):
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    process = subprocess.Popen(COMMAND, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    output = bytearray()
    deadline = time.monotonic() + 12
    step = 0
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], .05)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    chunk = b''
                output.extend(chunk)
            if step < len(steps) and steps[step][0] in output:
                os.write(master, steps[step][1])
                step += 1
            if process.poll() is not None:
                break
        assert process.poll() is not None, name + ': timeout'
        while select.select([master], [], [], 0)[0]:
            output.extend(os.read(master, 65536))
        assert process.returncode == code, name + ': exit status'
        assert expected in output, name + ': missing result'
        assert all(value not in output for value in forbidden), name + ': input echoed'
        assert termios.tcgetattr(slave) == original, name + ': terminal settings not restored'
        print('PASS:', name)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)


ACK = (b'Press Y to acknowledge', b'y')
ACCOUNT = b'Fake account input:'
PASSWORD = b'Fake password input:'
REJECTED = b'no credential transmission; owned buffers cleared.'
scenario('two legs and backspace', [ACK, (ACCOUNT, b'synthetiX\x7fc\r'), (PASSWORD, b'fake_secret\r')],
         b'PASS: both exact synthetic credential legs', 0, (b'synthetiX',))
scenario('uppercase acknowledgment', [(b'Press Y to acknowledge', b'Y'), (ACCOUNT, b'synthetic\r'), (PASSWORD, b'fake_secret\r')],
         b'PASS: both exact synthetic credential legs', 0)
scenario('decline', [(b'Press Y to acknowledge', b'n')], b'Declined; no credential transmission.', 3)
scenario('wrong account', [ACK, (ACCOUNT, b'PRIVATE_SENTINEL_A\r'), (PASSWORD, b'PRIVATE_SENTINEL_B\r')], REJECTED, 3,
         (b'PRIVATE_SENTINEL_A', b'PRIVATE_SENTINEL_B'))
scenario('escape account', [ACK, (ACCOUNT, b'PRIVATE_CANCEL\x1b')], REJECTED, 3, (b'PRIVATE_CANCEL',))
scenario('ctrl-c password', [ACK, (ACCOUNT, b'synthetic\r'), (PASSWORD, b'PRIVATE_CANCEL\x03')], REJECTED, 3,
         (b'PRIVATE_CANCEL',))
scenario('overflow', [ACK, (ACCOUNT, b'Z' * 256)], REJECTED, 3, (b'ZZZZ',))
scenario('non-ASCII', [ACK, (ACCOUNT, '密'.encode())], REJECTED, 3, ('密'.encode(),))
scenario('empty', [ACK, (ACCOUNT, b'\r')], REJECTED, 3)
scenario('cancel after input', [ACK, (ACCOUNT, b'synthetic\r'), (PASSWORD, b'fake_secret\r\x03')],
         b'Terminal synthetic check stopped or failed', 1)
scenario('EOF character', [ACK, (ACCOUNT, b'\x04')], REJECTED, 3)
scenario('control character', [ACK, (ACCOUNT, b'\t')], REJECTED, 3)
# Check each stream separately. Refusal happens before terminal changes or listeners.
for stream in ('stdin', 'stdout', 'stderr'):
    master, slave = pty.openpty()
    handles = dict(stdin=slave, stdout=slave, stderr=slave)
    handles[stream] = subprocess.PIPE
    process = subprocess.Popen(COMMAND, **handles)
    try:
        process.communicate(timeout=5)
        assert process.returncode == 2, 'redirection refusal: ' + stream
        print('PASS: redirected', stream)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)
# Closing the PTY master is real terminal loss, not an EOF character. There is no
# restoration assertion on a terminal that no longer exists, only bounded exit.
for partial in (False, True):
    master, slave = pty.openpty()
    process = subprocess.Popen(COMMAND, stdin=slave, stdout=slave, stderr=slave)
    try:
        output = bytearray()
        deadline = time.monotonic() + 5
        sent_ack = sent_account = False
        target = PASSWORD if partial else b'Press Y to acknowledge'
        while target not in output and time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                output.extend(os.read(master, 65536))
            if partial and not sent_ack and b'Press Y to acknowledge' in output:
                os.write(master, b'y')
                sent_ack = True
            if partial and not sent_account and ACCOUNT in output:
                os.write(master, b'synthetic\r')
                sent_account = True
        assert target in output, 'hangup: prompt missing'
        if partial:
            os.write(master, b'HANGUP_SENTINEL')
            time.sleep(.1)
        os.close(master)
        master = None
        assert process.wait(timeout=5) != 0, 'hangup must not succeed'
        print('PASS: terminal hangup exits without success', 'during password' if partial else 'during acknowledgment')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if master is not None:
            os.close(master)
        os.close(slave)
print('Terminal PTY checks passed (POSIX only; no Windows/macOS claim).')

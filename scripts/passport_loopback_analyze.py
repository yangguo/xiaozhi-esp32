#!/usr/bin/env python3
"""Decode Passport LBK logs, preserve gaps in stereo WAV, and report offline correlation.

Only Python's standard library is required. WAV channels retain wire order (L,R).
Positive raw lag means L follows R. No result here establishes AEC performance.
"""
import argparse
import base64
import binascii
import json
import math
from pathlib import Path
import re
import statistics
import struct
import sys
import wave
import zlib

RATE = 16000
BLOCK_FRAMES = 160
MAX_BLOCKS = 360000  # Firmware maximum: 3600 seconds, bounded parser input.
LINE = re.compile(r"\bLBK (\d+) (\d+) ([0-9a-fA-F]{8}) ([A-Za-z0-9+/=]+)\s*$")


def fields(line):
    result = {}
    for key, value in re.findall(r"(\w+)=([^\s]+)", line):
        try:
            result[key] = float(value) if "." in value else int(value)
        except ValueError:
            result[key] = value
    return result


def parse_log(lines):
    """Return separate runs; damaged/duplicate blocks never overwrite validated PCM."""
    runs = []
    current = None
    for line in lines:
        if "LBK_BEGIN " in line:
            current = dict(metadata=fields(line), blocks={}, stats=[], end={},
                           crc_errors=0, malformed=0, duplicates=0, reordered=0)
            runs.append(current)
        if current is None:
            if not re.search(r"\bLBK(?: |_)", line):
                continue
            current = dict(metadata={}, blocks={}, stats=[], end={}, crc_errors=0,
                           malformed=0, duplicates=0, reordered=0)
            runs.append(current)
        if "LBK_STAT " in line:
            current["stats"].append(fields(line))
        elif "LBK_END " in line:
            current["end"] = fields(line)
        elif re.search(r"\bLBK ", line):
            match = LINE.search(line)
            if not match:
                current["malformed"] += 1
                continue
            seq, length = int(match[1]), int(match[2])
            if seq >= MAX_BLOCKS or length != BLOCK_FRAMES * 4:
                current["malformed"] += 1
                continue
            try:
                pcm = base64.b64decode(match[4], validate=True)
            except (ValueError, binascii.Error):
                current["malformed"] += 1
                continue
            if len(pcm) != length or zlib.crc32(pcm) != int(match[3], 16):
                current["crc_errors"] += 1
                continue
            blocks = current["blocks"]
            if seq in blocks:
                current["duplicates"] += 1
                continue
            if blocks and seq < current.get("highest_sequence", -1):
                current["reordered"] += 1
            blocks[seq] = pcm
            current["highest_sequence"] = max(seq, current.get("highest_sequence", -1))
    return runs


def correlate(mic, ref, max_lag):
    """Mean-free normalized correlation; deterministic, bounded pure Python path.

    A common decimated set of positions evaluates EVERY integer lag, avoiding
    quantization of the delay. Signed coefficient retains polarity inversion.
    """
    size = min(len(mic), len(ref))
    limit = min(max_lag, (size - 16) // 2)
    if limit < 0:
        return 0, 0.0
    positions = range(limit, size - limit, max(1, (size - 2 * limit) // 256))
    ys = [ref[i] for i in positions]
    n = len(ys)
    sy = sum(ys)
    yy = sum(y*y for y in ys) - sy*sy/n
    if yy <= 1:
        return 0, 0.0
    best = (0, 0.0)
    for lag in range(-limit, limit + 1):
        xs = [mic[i + lag] for i in positions]
        sx = sum(xs)
        xx = sum(x*x for x in xs) - sx*sx/n
        if xx <= 1:
            continue
        xy = sum(x*y for x, y in zip(xs, ys)) - sx*sy/n
        corr = xy / math.sqrt(xx * yy)
        if abs(corr) > abs(best[1]):
            best = lag, corr
    return best


def signal(frame, rate=RATE):
    t = (frame % rate) / rate
    if t >= 0.8:
        return 0
    a = math.log(16) / 0.8
    envelope = min(1, t / 0.01, (0.8 - t) / 0.01)
    return int(4000 * envelope * math.sin(2 * math.pi * 200 * math.expm1(a*t) / a))


def channels(pcm):
    samples = struct.unpack('<' + 'h'*(len(pcm)//2), pcm)
    return samples[::2], samples[1::2]


def analyze(run, wav_path, max_lag=320):
    metadata, blocks = run['metadata'], run['blocks']
    for key, expected in [('rate', RATE), ('channels', 2), ('bits', 16),
                          ('block_frames', BLOCK_FRAMES)]:
        if metadata.get(key, expected) != expected:
            raise ValueError(f'unsupported {key}: {metadata[key]}')
    if not blocks:
        raise ValueError('no validated PCM blocks (enable CONFIG_PASSPORT_LOOPBACK_EXPORT_PCM)')
    total = run['end'].get('blocks', metadata.get('seconds', 0) * 100)
    total = max(total, max(blocks) + 1)
    if not isinstance(total, int) or not 0 < total <= MAX_BLOCKS:
        raise ValueError('invalid run length')
    missing = [i for i in range(total) if i not in blocks]
    zero = bytes(BLOCK_FRAMES * 4)
    with wave.open(str(wav_path), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        for seq in range(total):
            wav.writeframesraw(blocks.get(seq, zero))
    windows = []
    energy = [0, 0]
    clips = [0, 0]
    sample_count = 0
    for pcm in blocks.values():
        for ch, samples in enumerate(channels(pcm)):
            energy[ch] += sum(x*x for x in samples)
            clips[ch] += sum(abs(x) >= 32760 for x in samples)
        sample_count += BLOCK_FRAMES
    template_scores = None
    # Use the active middle of each sweep; reject an entire window with any gap.
    for second in range((total + 99)//100):
        indices = range(second*100 + 20, second*100 + 70)
        if not all(i in blocks for i in indices):
            continue
        left, right = channels(b''.join(blocks[i] for i in indices))
        lag, corr = correlate(left, right, max_lag)
        windows.append(dict(second=second, lag_samples=lag, lag_ms=lag*1000/RATE,
                            correlation=corr, valid=abs(corr) >= 0.2))
        if template_scores is None:
            template = [signal(second*RATE + 3200+i) for i in range(len(left))]
            template_scores = [correlate(ch, template, max_lag)[1] for ch in (left, right)]
    good = [w['lag_samples'] for w in windows if w['valid']]
    median = statistics.median(good) if good else None
    for w in windows:
        w['drift_samples'] = w['lag_samples'] - median if median is not None and w['valid'] else None
    # Causal inference, not electrical proof: a clean DAC reference should precede acoustic mic.
    reference = 'R' if median is not None and median > 0 else (
        'L' if median is not None and median < 0 else 'ambiguous')
    device_errors = any(run['end'].get(k, 0) for k in
                        ('capture_errors', 'export_drops', 'rx_overflows', 'tx_errors'))
    report = dict(rate=RATE, wav_channels=['L (wire slot 0)', 'R (wire slot 1)'],
                  frames=total*BLOCK_FRAMES, missing_blocks=len(missing),
                  missing_sequences=missing, crc_errors=run['crc_errors'],
                  malformed=run['malformed'], duplicates=run['duplicates'], reordered=run['reordered'],
                  complete=not missing and not run['crc_errors'] and not device_errors
                           and bool(run['end']) and not run['malformed'],
                  inferred_reference=reference,
                  mapping_basis='causal lead; confirm with near-end-only speech and template scores',
                  template_correlations=template_scores,
                  raw_L_follows_R_samples=median,
                  mic_delay_samples=abs(median) if median is not None else None,
                  mic_delay_ms=abs(median)*1000/RATE if median is not None else None,
                  max_drift_ms=max((abs(x-median)*1000/RATE for x in good), default=None),
                  rms=[math.sqrt(x/sample_count) for x in energy], clipping_samples=clips,
                  windows=windows, device_stats=run['stats'], device_end=run['end'],
                  metadata=metadata,
                  limitations='No proof of DMA sample continuity; overflow events have unknown sample count. '
                              'Correlation search bounded; silence/uncorrelated windows excluded. '
                              'Template scores assume nominal stream alignment; inspect WAV manually.')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', nargs='?', default='-', help='serial log or - for stdin')
    parser.add_argument('--wav', type=Path, default=Path('loopback.wav'))
    parser.add_argument('--report', type=Path, default=Path('loopback-report.json'))
    parser.add_argument('--run', type=int, default=-1, help='zero-based run index, default last')
    parser.add_argument('--max-lag', type=int, default=320, help='search radius in samples')
    args = parser.parse_args(argv)
    if not 1 <= args.max_lag <= RATE//4:
        parser.error('--max-lag must be 1..4000')
    try:
        if args.log == '-':
            runs = parse_log(sys.stdin)
        else:
            with open(args.log, encoding='utf-8', errors='replace') as log:
                runs = parse_log(log)
        if not runs:
            raise ValueError('no LBK run found')
        run = runs[args.run]
        if not run['blocks']:
            # Stats-only captures remain useful without pretending a WAV exists.
            report = {k: v for k, v in run.items() if k != 'blocks'}
            report['complete'] = False
            report['note'] = 'No raw PCM; statistics only, no WAV written'
        else:
            report = analyze(run, args.wav, args.max_lag)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, IndexError) as error:
        print(f'loopback analysis failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

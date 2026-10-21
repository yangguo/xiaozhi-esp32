"""Offline PCM framing, channel mapping, delay and shared firmware DSP checks."""
import base64
import importlib.util
import math
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import unittest
import wave
import zlib

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('loopback', ROOT/'scripts/passport_loopback_analyze.py')
lbk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lbk)


def line(seq, pcm, crc=None):
    crc = zlib.crc32(pcm) if crc is None else crc
    return f'prefix LBK {seq} {len(pcm)} {crc:08x} {base64.b64encode(pcm).decode()}\n'


def log_data(delay=41, swap=False, seconds=1):
    rng = random.Random(10)
    ref = [rng.randint(-4000, 4000) for _ in range(seconds*16000)]
    lines = [f'LBK_BEGIN rate=16000 channels=2 bits=16 block_frames=160 seconds={seconds}\n']
    for seq in range(seconds*100):
        samples = []
        for i in range(seq*160, (seq+1)*160):
            mic = ref[i-delay]//2 if i >= delay else 0
            samples.extend((ref[i], mic) if swap else (mic, ref[i]))
        lines.append(line(seq, struct.pack('<320h', *samples)))
    lines += ['LBK_STAT sec=0 mic_rms=12.5 ref_rms=25.0 lag_samples=41 corr=0.99\n',
              f'LBK_END blocks={seconds*100} capture_errors=0 export_drops=0 rx_overflows=0 tx_errors=0\n']
    return lines


class AnalyzeTests(unittest.TestCase):
    def analyze(self, lines):
        run = lbk.parse_log(lines)[0]
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory)/'stereo.wav'
            report = lbk.analyze(run, wav, 80)
            with wave.open(str(wav)) as audio:
                self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()),
                                 (2, 2, 16000))
                self.assertEqual(audio.getnframes(), report['frames'])
                pcm = audio.readframes(audio.getnframes())
        return report, pcm

    def test_known_delay(self):
        report, _ = self.analyze(log_data())
        self.assertEqual(report['mic_delay_samples'], 41)
        self.assertEqual(report['inferred_reference'], 'R')
        self.assertGreater(report['windows'][0]['correlation'], 0.999)
        self.assertEqual(report['max_drift_ms'], 0)
        self.assertTrue(report['complete'])
        self.assertEqual(report['device_stats'][0]['mic_rms'], 12.5)

    def test_swapped_channels(self):
        report, _ = self.analyze(log_data(swap=True))
        self.assertEqual(report['inferred_reference'], 'L')
        self.assertEqual(report['raw_L_follows_R_samples'], -41)
        self.assertEqual(report['mic_delay_samples'], 41)

    def test_crc_and_missing_blocks_preserve_time(self):
        lines = log_data()
        lines[6] = lines[6].replace(lines[6].split()[4], '00000000')
        # Replace CRC explicitly, retaining otherwise valid framing.
        words = lines[7].split()
        words[4] = '00000000'
        lines[7] = ' '.join(words)+'\n'
        del lines[11]
        report, pcm = self.analyze(lines)
        self.assertEqual(report['crc_errors'], 2)
        self.assertEqual(report['missing_blocks'], 3)
        self.assertFalse(report['complete'])
        self.assertEqual(pcm[5*640:6*640], bytes(640))

    def test_late_and_duplicate_blocks(self):
        lines = log_data()
        lines[1], lines[2] = lines[2], lines[1]
        lines.insert(3, lines[1])
        report, _ = self.analyze(lines)
        self.assertEqual(report['duplicates'], 1)
        self.assertEqual(report['reordered'], 1)
        self.assertEqual(report['missing_blocks'], 0)

    def test_drift(self):
        one = log_data(delay=32)
        two = log_data(delay=48)
        lines = [one[0].replace('seconds=1', 'seconds=2')] + one[1:101]
        for text in two[1:101]:
            words = text.split()
            words[2] = str(int(words[2])+100)
            lines.append(' '.join(words)+'\n')
        lines.append('LBK_END blocks=200\n')
        report, _ = self.analyze(lines)
        self.assertEqual(report['mic_delay_samples'], 40)
        self.assertEqual(report['max_drift_ms'], 0.5)

    def test_multiple_runs_silence_and_validation(self):
        lines = ['LBK_BEGIN seconds=1\n', line(0, bytes(640)), 'LBK_END blocks=100\n']
        runs = lbk.parse_log(lines + lines)
        self.assertEqual(len(runs), 2)
        report, _ = self.analyze(lines)
        self.assertEqual(report['inferred_reference'], 'ambiguous')
        self.assertIsNone(report['mic_delay_samples'])
        runs[0]['metadata']['rate'] = 24000
        with self.assertRaises(ValueError):
            lbk.analyze(runs[0], Path('/tmp/unused.wav'))

    def test_chirp_delay_and_stats_only_cli(self):
        ref = [lbk.signal(i) for i in range(8000)]
        self.assertEqual(lbk.correlate([0]*35+ref[:-35], ref, 80)[0], 35)
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory)/'stats.json'
            log = Path(directory)/'stats.log'
            log.write_text('LBK_BEGIN rate=16000\nLBK_STAT sec=0 ref_rms=0\nLBK_END blocks=100\n')
            result = subprocess.run(['python3', str(ROOT/'scripts/passport_loopback_analyze.py'),
                                     str(log), '--report', str(report)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('statistics only', report.read_text())


class FirmwareDspTests(unittest.TestCase):
    def test_shared_chirp_correlation_crc_and_base64(self):
        source = r'''
#include "passport_loopback_dsp.h"
#include <cassert>
#include <cstdio>
#include <cstring>
using namespace passport_loopback;
int main() {
    assert(Signal(14000) == 0);
    int16_t pcm[1280]{};
    uint32_t rng = 123;
    for (int i = 0; i < 640; ++i) {
        rng = rng*1664525+1013904223;
        pcm[2*i+1] = int16_t(rng >> 16);
    }
    for (int i = 23; i < 640; ++i) pcm[2*i] = pcm[2*(i-23)+1]/2;
    auto result = Correlate(pcm, 640, 160);
    assert(result.lag == 23 && result.peak > 0.999);
    const auto* data = reinterpret_cast<const uint8_t*>("123456789");
    assert(Crc32(data, 9) == 0xcbf43926);
    char b64[16];
    Base64(data, 9, b64); assert(strcmp(b64, "MTIzNDU2Nzg5") == 0);
    Base64(data, 1, b64); assert(strcmp(b64, "MQ==") == 0);
    Base64(data, 2, b64); assert(strcmp(b64, "MTI=") == 0);
    for (int i : {0, 1, 160, 4000, 12000, 15999}) printf("%d %d\n", i, Signal(i));
}
'''.replace('#include <cstring>', '#include <cstring>\n#include <initializer_list>')
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory)/'dsp.cc'
            binary = Path(directory)/'dsp'
            cpp.write_text(source)
            subprocess.check_call(['g++', '-std=c++23', '-Wall', '-Wextra', '-Werror',
                                   '-I'+str(ROOT/'main/boards/folotoy/ai-passport'),
                                   str(cpp), '-o', str(binary)])
            for text in subprocess.check_output([str(binary)], text=True).splitlines():
                i, sample = map(int, text.split())
                self.assertLessEqual(abs(sample-lbk.signal(i)), 1)


if __name__ == '__main__':
    unittest.main()

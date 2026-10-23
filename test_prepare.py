import unittest
from prepare_local import plan


class PreparationTests(unittest.TestCase):
    def metadata(self, duration=600, audio=1, video=True):
        return {'format': {'duration': str(duration)}, 'streams':
                ([{'codec_type': 'video'}] if video else []) + [{'codec_type': 'audio'}]*audio}

    def test_first_three_audio_tracks_only(self):
        self.assertEqual(plan(self.metadata(audio=5)), (600, 3))
        self.assertEqual(plan(self.metadata(audio=1)), (600, 1))

    def test_short_source_is_not_silently_padded(self):
        with self.assertRaises(ValueError): plan(self.metadata(duration=479))

    def test_audio_and_video_required_for_this_trial(self):
        with self.assertRaises(ValueError): plan(self.metadata(audio=0))
        with self.assertRaises(ValueError): plan(self.metadata(video=False))


if __name__ == '__main__': unittest.main()

import type { Preferences } from './types';
export function classroomPreset(draft: Preferences): Preferences {
  return {...draft,asr_language_mode:'ko_en',asr_hotword_weight:4,
    asr_acoustic_profile:'far',audio_processing_mode:'standard'};
}

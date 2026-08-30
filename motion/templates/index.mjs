// index.mjs — template registry. All templates render with signature:
//   render(ctx, {W, H}, props, t, palette, helpers)
// where t is local progress in [0,1].
//
// Composition templates (thin wrappers over the primitives, §6):
//   zoom_sequence      — sequence of reveal/zoom beats
//   scientific_process — sequence of diagram/callout steps
//   character_intro    — reveal + callout composition
import kinetic_title from "./kinetic_title.mjs";
import timeline from "./timeline.mjs";
import map_zoom from "./map_zoom.mjs";
import infographic from "./infographic.mjs";
import comparison from "./comparison.mjs";
import diagram from "./diagram.mjs";
import callout from "./callout.mjs";
import number_counter from "./number_counter.mjs";
import quote_card from "./quote_card.mjs";
import before_after from "./before_after.mjs";
import reveal from "./reveal.mjs";
import sequence from "./sequence.mjs";

export const TEMPLATES = {
  kinetic_title,
  timeline,
  map_zoom,
  infographic,
  comparison,
  diagram,
  callout,
  number_counter,
  quote_card,
  before_after,
  reveal,
  // Compositions (all three map to the sequence runner).
  zoom_sequence: sequence,
  scientific_process: sequence,
  character_intro: sequence,
};

export const COMPOSITION_TEMPLATES = new Set([
  "zoom_sequence", "scientific_process", "character_intro",
]);

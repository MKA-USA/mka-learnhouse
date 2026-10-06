// Preloaded for every `bun test` run (see bunfig.toml).
//
// Radix (and other libraries) decide at MODULE LOAD time whether `globalThis.document` exists, e.g.
// `useLayoutEffect = globalThis?.document ? React.useLayoutEffect : () => {}`. Several test files import
// components that pull Radix in at the top level (mka-compliance-format -> badges -> tooltip). If one of them is
// loaded before a DOM test installs happy-dom, Radix is cached in its "no DOM" form for the whole process and
// every Popover/Portal silently never mounts. Which test file loads first depends on the run, so the DOM
// tests failed depending on file order. Installing the DOM once, before any test file loads, removes the dependency.
import { Window } from "happy-dom";

const domWindow = new Window({ url: "http://localhost/" });
for (const key of [
  "document", "navigator", "HTMLElement", "Element", "Node", "Text", "DocumentFragment", "MutationObserver",
  "Range", "Selection", "DOMParser", "getComputedStyle", "requestAnimationFrame", "cancelAnimationFrame",
  "KeyboardEvent", "MouseEvent", "InputEvent", "NodeFilter", "DOMException", "HTMLInputElement", "ClipboardEvent",
  "HTMLIFrameElement", "SVGElement", "FocusEvent", "PointerEvent",
]) {
  if (domWindow[key] !== undefined && globalThis[key] === undefined) globalThis[key] = domWindow[key];
}
globalThis.window = domWindow;

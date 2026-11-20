// TeX -> SVG for formula lines in notes (engine/scene.py, render_math). Reads a JSON list of TeX strings on stdin, writes a JSON list
// of {svg, w, h, error} (w, h in ex). Paths are inlined (fontCache: none): no <use>/<defs>, which the board's sanitiser would drop.
import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js';

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const packages = AllPackages.filter(p => !['html', 'require', 'autoload', 'bussproofs'].includes(p));   // no packages that load or emit HTML
const doc = mathjax.document('', { InputJax: new TeX({ packages, formatError: (_jax, err) => { throw err; } }), OutputJax: new SVG({ fontCache: 'none' }) });

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
  const out = JSON.parse(input).map(tex => {
    try {
      const node = doc.convert(String(tex), { display: true });
      const svg = adaptor.firstChild(node);
      return { svg: adaptor.outerHTML(svg), w: parseFloat(adaptor.getAttribute(svg, 'width')), h: parseFloat(adaptor.getAttribute(svg, 'height')) };
    } catch (e) {
      return { error: String(e.message || e).slice(0, 200) };
    }
  });
  process.stdout.write(JSON.stringify(out));
});

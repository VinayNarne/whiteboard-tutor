// Reads a JSON array of ELK graphs on stdin, lays each one out, writes the JSON array of results to stdout.
// Called by engine/scene.py; one process per scene (both reading directions are laid out in one call).
import ELK from 'elkjs/lib/elk.bundled.js';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const elk = new ELK();
const graphs = JSON.parse(input);
const out = await Promise.all(graphs.map(g => elk.layout(g)));
process.stdout.write(JSON.stringify(out));

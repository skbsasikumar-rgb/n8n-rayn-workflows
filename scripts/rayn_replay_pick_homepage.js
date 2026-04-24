#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

function usage() {
  console.error('Usage: node scripts/rayn_replay_pick_homepage.js <fixture.json>');
  process.exit(1);
}

const fixturePath = process.argv[2];
if (!fixturePath) usage();

const workflowPath = path.resolve(process.cwd(), 'wf-worker.json');
const workflow = JSON.parse(fs.readFileSync(workflowPath, 'utf8'));
const node = workflow.nodes.find((entry) => entry.name === 'Pick First Valid Homepage');
if (!node) {
  console.error('Pick First Valid Homepage node not found in wf-worker.json');
  process.exit(1);
}

const fixture = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), fixturePath), 'utf8'));
const normalizeInput = fixture.normalizeInput || {};
const searchHomepageSimple = fixture.searchHomepageSimple || {};
const inputItems = Array.isArray(fixture.inputItems) ? fixture.inputItems : [];

const code = node.parameters.jsCode;

function $(name) {
  if (name === 'Normalize Input') {
    return {
      first: () => ({ json: normalizeInput }),
      item: { json: normalizeInput },
    };
  }
  if (name === 'Search Homepage Simple') {
    return {
      first: () => ({ json: searchHomepageSimple }),
      item: { json: searchHomepageSimple },
    };
  }
  return {
    first: () => ({ json: {} }),
    item: { json: {} },
  };
}

const $input = {
  all: () => inputItems.map((json) => ({ json })),
};

try {
  const fn = new Function('$', '$input', code);
  const result = fn($, $input);
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}

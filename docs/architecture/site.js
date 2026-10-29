"use strict";
// What is mneme-llm's own on the architecture page: the top map (after docs/DESIGN.md, "The shape") and the guide
// "One exchange, end to end" (after its section 3). app.js, diagram.js and style.css are the same viewer as in
// DiscordStudyBot's page (the project that first used mneme-llm); this file is what differs.
window.SITE = (() => {
  const P = "mneme_llm";
  const GUIDE = "guide/exchange";

  function topChart(h) {
    const { files, link, plural, firstLine, filesUnder, fileLink, symbolLink } = h;
    const chart = new h.Chart("DOWN", { overview: true });
    const file = (name, label, sub, kind = "file") => chart.node(label, {
      kind, sub, target: fileLink(`${P}/${name}`), tip: firstLine(files[`${P}/${name}`]?.doc) });
    const app = chart.group("Your application (any model)", () => {
      chart.node("aprompt() before a reply", { kind: "function", sub: "who they are, notes and what was said before, mood news",
                                               target: symbolLink(`${P}/__init__.py`, "Mneme.aprompt") });
      chart.node("aobserve() after it", { kind: "function", sub: "the exchange kept word for word; the mood judged; notes written",
                                          target: symbolLink(`${P}/__init__.py`, "Mneme.aobserve") });
    }, { kind: "interfaces", pack: true });
    const outside = chart.group("Or through", () => {
      file("tools.py", "tools.py", "tool definitions (five API styles), the dispatcher");
      file("mcp.py", "mcp.py", "an MCP server over stdio");
      file("cli.py", "cli.py", "the mneme-llm command");
    }, { kind: "interfaces", pack: true });
    const facade = chart.node("Mneme", { kind: "manager", sub: "one space · builds every part from the config · makes the model calls",
                                         target: symbolLink(`${P}/__init__.py`, "Mneme"), tip: firstLine(files[`${P}/__init__.py`]?.doc) });
    const parts = {};
    // Memory, Episodes and Mood have edges of their own (to their tiers), which a packed group cannot route; the
    // others pack.
    const owners = chart.group("The parts: each kind of row has one owner", () => {
      parts.memory = file("memory.py", "Memory", "notes · recall · profile card · recall log", "class");
      parts.episodes = file("episodes.py", "Episodes", "what was said, word for word · the look · search · fading", "class");
      parts.mood = file("mood.py", "Mood", "value and feelings · fading · told once", "class");
      chart.group("and", () => {
        file("relations.py", "Relations", "who each person is to it · closeness", "class");
        file("aliases.py", "Aliases", "what each person calls it", "class");
        file("people.py", "People", "one person under several accounts", "class");
        file("config.py", "Config", "prompts, sentences, roles, settings: in the file", "class");
        file("capture.py", "capture", "the note writer and the profile writer");
      }, { kind: "plain", pack: true });
    }, { kind: "core" });
    const meaning = chart.group("meaning/ · finding notes by meaning", () => {
      const embed = file("meaning/embedders.py", "1 · embeddings", "a vector for the query");
      const centroids = file("meaning/micro.py", "2 · word centroids", "removable: learned from the notes");
      const unify = file("meaning/unify.py", "3 · unify", "removable: glosses, the query translated");
      chart.edge(embed, centroids, { label: "else" });
      chart.edge(centroids, unify, { label: "else" });
      file("meaning/calibrate.py", "calibrate", "each embedding model's floor");
      file("meaning/ledger.py", "ledger", "what notes taught the centroids");
    }, { kind: "capabilities" });
    const decide = chart.group("decide/ · the mood, and what is worth keeping", () => {
      const luna = file("decide/luna.py", "1 · Luna", "OpenAI's Decisions API");
      const micro = file("decide/micro.py", "2 · micro", "removable: local models learned from Luna");
      const prompt = file("decide/prompt.py", "3 · your model", "asked for JSON");
      chart.edge(luna, micro, { label: "else" });
      chart.edge(micro, prompt, { label: "else" });
    }, { kind: "watchers" });
    const store = file("store.py", "Store", "one SQLite file · schema 1 · transactions", "store");
    const shared = chart.group("Shared by all", () => {
      for (const [name, sub] of [["providers.py", "calling out: sync or async, JSON"], ["text.py", "words, scripts, clipping"],
                                 ["dates.py", "human dates"], ["i18n.py", "every sentence, English and Chinese"],
                                 ["prompts.py", "every instruction to a model"], ["exchange.py", "an exchange as lines, framed for a judge"]]) {
        file(name, name, sub);
      }
    }, { kind: "plain", pack: true });
    for (const root of h.A.roots.filter((item) => item !== P)) {
      chart.node(`${root}/`, { kind: "folder", sub: plural(filesUnder(root).length, "file"), target: link(root) });
    }
    chart.node("One exchange, end to end", { kind: "guide", sub: "what aprompt and aobserve do", target: link(GUIDE) });
    chart.edge(app, facade, { label: "aprompt · aobserve" });
    chart.edge(outside, facade, { dashed: true });
    chart.edge(facade, owners, { label: "builds · calls" });
    chart.edge(parts.memory, meaning, { label: "notes close in meaning" });
    chart.edge(parts.episodes, meaning, { label: "exchanges close in meaning" });
    chart.edge(parts.mood, decide, { label: "judged" });
    chart.edge(owners, store, { label: "rows" });
    chart.edge(meaning, store, { dashed: true, label: "vectors" });
    chart.edge(owners, shared, { dashed: true, arrow: "none" });
    return chart;
  }

  function topPane(h) {
    const { make, link, linkList, heading, github } = h;
    const pane = [...heading("Architecture", "mneme-llm")];
    pane.push(make("div", "doc", "Memory and mood for any language model, in one SQLite file. Every box is a real " +
      "folder, file, class or function, read from the code by tools/architecture.py. Click a box (or search above) to " +
      "go deeper: a folder, a file (its classes drawn around their methods), and one function, whose code shows here."));
    pane.push(make("p", "meta", h.counts()));
    pane.push(make("h3", "", "Read first"));
    pane.push(linkList([["One exchange, end to end", link(GUIDE)],
                        ["README: using it", github("README.md")],
                        ["How it works (DESIGN.md)", github("docs/DESIGN.md")],
                        ["The file format (FORMAT.md)", github("docs/FORMAT.md")],
                        ["What changed (CHANGELOG.md)", github("CHANGELOG.md")]]));
    pane.push(make("h3", "", "Layers"));
    pane.push(make("div", "doc", "Dependencies point one way: text, dates, i18n, prompts, providers, exchange and the " +
      "store import nothing above them; decide and meaning build on providers; memory and episodes use meaning and the store; the " +
      "mood uses decide's types; Mneme wires the parts together and makes the calls to models; tools, MCP and the CLI " +
      "sit on Mneme. Each kind of row has one owner that writes it, and every write looks up the person a subject " +
      "stands for inside its own transaction."));
    pane.push(make("h3", "", "Removable tiers"));
    pane.push(make("div", "doc", "decide/micro.py, meaning/micro.py and meaning/unify.py can each be deleted and " +
      "everything else works (tests/test_removable.py, and a CI job runs the whole suite without them)."));
    return pane;
  }

  // ---- the guide: one exchange, end to end ------------------------------------------------------------------
  function guideChart(h) {
    const { symbolLink } = h;
    const chart = new h.Chart("DOWN", { overview: true });
    const step = (label, sub, path, id, kind = "function") => chart.node(label, { kind, sub, target: symbolLink(`${P}/${path}`, id) });
    const chain = (items) => items.reduce((before, item) => { chart.edge(before, item); return item; });
    const before = chart.group("Before the reply: aprompt(subject, query)", () => {
      chain([
        step("Mneme.aprompt", "the text for the system prompt", "__init__.py", "Mneme.aprompt"),
        step("Memory.acontext → arecall", "the notes for this message", "memory.py", "Memory.arecall"),
        step("Meaning.find", "embeddings → centroids → unify", "meaning/__init__.py", "Meaning.find"),
        step("Memory._rank", "shared words + meaning × freshness × importance", "memory.py", "Memory._rank"),
        step("Memory._render", "\"these are data\" · profile card · dated notes", "memory.py", "Memory._render"),
        step("Episodes.alook", "with said=: what was said before, word for word, faded ones counting less", "episodes.py", "Episodes.alook"),
        step("Episodes._ranked", "BM25 + closeness in meaning, fused by rank × retention", "episodes.py", "Episodes._ranked"),
        step("Mneme._prompt", "who they are · their name for it · notes · said before · mood news", "__init__.py", "Mneme._prompt"),
      ]);
    }, { kind: "capabilities" });
    const reply = chart.node("your model replies", { kind: "external", sub: "with that text in its prompt" });
    const after = chart.group("After the reply: aobserve(subject, exchange)", () => {
      chain([
        step("Mneme.aobserve", "once the reply is out", "__init__.py", "Mneme.aobserve"),
        step("Episodes.keep", "the exchange word for word (no model call)", "episodes.py", "Episodes.keep"),
        step("Chain.adecide", "one request: mood change, feeling, worth keeping? Luna → micro → your model", "decide/__init__.py", "Chain.adecide"),
        step("Mood.apply_answers", "a delta and feelings, scaled by closeness; a timeline event", "mood.py", "Mood.apply_answers"),
        step("Relations.seen", "a day of contact: closeness grows once a day", "relations.py", "Relations.seen"),
        step("Mneme._capture", "worth it? the note writer (your model)", "__init__.py", "Mneme._capture"),
        step("Memory.keep", "the rules of writing: one live note per key, a daily quota", "memory.py", "Memory.keep"),
        step("Episodes.prepare", "its vector; it rehearses the earlier exchanges it is about", "episodes.py", "Episodes.prepare"),
      ]);
    }, { kind: "watchers" });
    chart.edge(before, reply);
    chart.edge(reply, after);
    return chart;
  }

  function guidePane(h) {
    const { make, heading, linkList, github, symbolLink } = h;
    const pane = [...heading("Guide", "One exchange, end to end")];
    pane.push(make("div", "doc", "A host calls two things around each reply of its model: aprompt before it (what the " +
      "companion knows of the person, for its prompt) and aobserve after it (how the exchange left it feeling, and " +
      "what is worth keeping). The boxes open the real code; the full account is docs/DESIGN.md, section 3."));
    const steps = [
      ["Before the reply", "aprompt(subject, query, user_name) puts together: who the person is to the companion (a " +
        "role and closeness), what they call it, its notes for this message, and its mood's news (the newest " +
        "confident change, told once). The notes come from arecall: the subject's live notes (their 5,000 most " +
        "valuable when there are more), the query placed among them by the first meaning tier that can (embeddings, " +
        "then word centroids, then unify's translation), ranked by shared words and closeness in meaning, weighted " +
        "by freshness, importance and feeling, cut to a budget, and rendered under a line saying they are data, not " +
        "instructions. With said=, the look adds what was said before, word for word: BM25 over the exchanges' words " +
        "fused with closeness in meaning, each faded exchange counting less, within a budget of characters, under a " +
        "header asking the model to check it is about the same person and the same thing."],
      ["After the reply", "aobserve(subject, exchange, source, user_name) first keeps the exchange word for word (when " +
        "the person started it), then asks one decision request (Luna, then the " +
        "local micro models once they have learned, then your model): how much the mood changes, which feeling, and " +
        "whether anything is worth remembering. The mood moves by how close the person is; an exchange the person " +
        "started is a day of contact; and when it is worth it, the note writer (your model) writes notes, kept under " +
        "the rules of writing (one live note per key, the newest; no text twice; a daily quota for automatic notes). " +
        "Last, the exchange gets its vector, and rehearses the earlier exchanges it is about: they fade slower."],
      ["What it costs", "Beyond the reply itself: one embeddings request before it (for the query; notes are embedded " +
        "once), one Luna request and one embeddings request (the exchange) after it, and a note-writer call only when " +
        "there is something to write."],
      ["One person, several accounts", "link(subject, person) makes an account another subject of a person: every " +
        "call with either means them, and what was kept under the account joins the person."],
    ];
    for (const [title, text] of steps) pane.push(make("h3", "", title), make("div", "doc", text));
    pane.push(make("h3", "", "In your code"));
    pane.push(make("div", "signature", "m = Mneme(\"companion.db\", space=\"dafeiyu\", complete=my_model)\n" +
      "system = PERSONA + \"\\n\\n\" + await m.aprompt(\"discord:42\", query=user_message, user_name=\"Leo\", said=6000)\n" +
      "reply = ...  # your model answers, with that system prompt\n" +
      "await m.aobserve(\"discord:42\", [(\"Leo\", user_message), (\"大肥鱼\", reply)], user_name=\"Leo\")"));
    pane.push(make("h3", "", "Read more"));
    pane.push(linkList([["Mneme, the facade", symbolLink(`${P}/__init__.py`, "Mneme")],
                        ["README: using it", github("README.md")], ["How it works (DESIGN.md)", github("docs/DESIGN.md")]]));
    return pane;
  }

  return {
    name: "mneme-llm",
    top: { chart: topChart, pane: topPane, title: "The whole package",
           hint: "Your application calls Mneme; Mneme builds the parts, and the parts keep their rows in one SQLite file." },
    guides: [{ path: GUIDE, label: "One exchange, end to end", keywords: "aprompt aobserve exchange guide how it works",
               chart: guideChart, pane: guidePane, title: "One exchange, end to end",
               hint: "What aprompt does before a reply and aobserve after it. Click a step for its code." }],
    deep: [P],
  };
})();

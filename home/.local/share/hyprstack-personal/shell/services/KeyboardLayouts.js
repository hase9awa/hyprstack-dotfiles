.pragma library

function parseRules(text) {
    const names = new Map();
    let section = "";
    for (const line of text.split(/\r?\n/)) {
        const header = line.match(/^!\s+(\w+)/);
        if (header) {
            section = header[1];
            continue;
        }
        if (section === "layout") {
            const match = line.match(/^\s*(\S+)\s+(.+?)\s*$/);
            if (match)
                names.set(match[2], match[1]);
        } else if (section === "variant") {
            const match = line.match(/^\s*\S+\s+([^\s:]+):\s*(.+?)\s*$/);
            if (match)
                names.set(match[2], match[1]);
        }
    }
    return names;
}

function code(keyboard, names) {
    if (!keyboard)
        return "??";
    const name = names.get(keyboard.activeKeymap);
    if (name)
        return name;
    const layouts = keyboard.layout.split(",").map(layout => layout.trim());
    const index = keyboard.lastIpcObject?.active_layout_index ?? -1;
    return layouts[index] || (layouts.length === 1 ? layouts[0] : "") || "??";
}

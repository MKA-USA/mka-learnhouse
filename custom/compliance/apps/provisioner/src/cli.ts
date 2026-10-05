#!/usr/bin/env bun
// Provisioner CLI skeleton (milestone 0). Subcommands arrive with the importer/generator work order.
import { DEPARTMENTS } from "@mka/compliance-core";

const cmd = process.argv[2];
switch (cmd) {
  case "departments":
    for (const d of DEPARTMENTS) console.log(`${d.slug}\t${d.name}\t${d.translation}\t${d.mailboxPrefix}`);
    break;
  default:
    console.log("usage: provisioner <departments>\n(planned: import, validate, render, provision, enroll; probe via `bun run probe`)");
}

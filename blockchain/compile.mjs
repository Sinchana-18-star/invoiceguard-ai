// Compile InvoiceRegistry.sol with solc-js and write the ABI + bytecode used by the Python app.
//   cd blockchain && npm install && node compile.mjs
import fs from "node:fs";
import solc from "solc";

const source = fs.readFileSync(new URL("./InvoiceRegistry.sol", import.meta.url), "utf8");
const input = {
  language: "Solidity",
  sources: { "InvoiceRegistry.sol": { content: source } },
  settings: { optimizer: { enabled: true, runs: 200 }, evmVersion: "paris",
              outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } } },
};
const output = JSON.parse(solc.compile(JSON.stringify(input)));
const errors = (output.errors || []).filter((e) => e.severity === "error");
if (errors.length) {
  console.error(errors.map((e) => e.formattedMessage).join("\n"));
  process.exit(1);
}
const c = output.contracts["InvoiceRegistry.sol"].InvoiceRegistry;
fs.writeFileSync(new URL("./InvoiceRegistry.json", import.meta.url),
  JSON.stringify({ contractName: "InvoiceRegistry", compiler: solc.version(), abi: c.abi,
                   bytecode: "0x" + c.evm.bytecode.object }, null, 2));
console.log(`Compiled InvoiceRegistry with solc ${solc.version()}`);

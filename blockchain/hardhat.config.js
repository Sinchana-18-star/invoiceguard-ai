// Local development chain for InvoiceGuard AI:  npx hardhat node --hostname 127.0.0.1 --port 8545
// (The app starts this automatically in INVOICEGUARD_LEDGER=local mode.)
module.exports = {
  solidity: "0.8.28",
  networks: { hardhat: { chainId: 31337 } },
};

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title InvoiceRegistry - a shared ledger of invoice fingerprints to stop double payment / double financing.
/// @notice Only a SHA-256 fingerprint of (supplier GSTIN, invoice number) is stored - never invoice data.
///         If a second organisation tries to register the same invoice, the call reverts and that
///         organisation's InvoiceGuard escalates the invoice as possible double financing.
contract InvoiceRegistry {
    uint8 public constant REGISTERED = 1;
    uint8 public constant APPROVED = 2;
    uint8 public constant REJECTED = 3;

    struct Record {
        address registrar;      // organisation that registered the invoice first
        uint64 registeredAt;
        uint8 status;
        bytes32 decisionHash;   // hash of the human decision + audit-log head at decision time
    }

    mapping(bytes32 => Record) public records;
    uint256 public totalRegistered;

    event InvoiceRegistered(bytes32 indexed invoiceKey, address indexed registrar);
    event DecisionRecorded(bytes32 indexed invoiceKey, uint8 status, bytes32 decisionHash);

    error AlreadyRegistered(bytes32 invoiceKey, address registrar);
    error NotRegistered(bytes32 invoiceKey);
    error NotRegistrar(bytes32 invoiceKey);

    function registerInvoice(bytes32 invoiceKey) external {
        Record storage r = records[invoiceKey];
        if (r.registrar != address(0)) revert AlreadyRegistered(invoiceKey, r.registrar);
        records[invoiceKey] = Record(msg.sender, uint64(block.timestamp), REGISTERED, bytes32(0));
        totalRegistered += 1;
        emit InvoiceRegistered(invoiceKey, msg.sender);
    }

    function recordDecision(bytes32 invoiceKey, bool approved, bytes32 decisionHash) external {
        Record storage r = records[invoiceKey];
        if (r.registrar == address(0)) revert NotRegistered(invoiceKey);
        if (r.registrar != msg.sender) revert NotRegistrar(invoiceKey);
        r.status = approved ? APPROVED : REJECTED;
        r.decisionHash = decisionHash;
        emit DecisionRecorded(invoiceKey, r.status, decisionHash);
    }

    function lookup(bytes32 invoiceKey) external view returns (address registrar, uint64 registeredAt, uint8 status,
                                                               bytes32 decisionHash) {
        Record storage r = records[invoiceKey];
        return (r.registrar, r.registeredAt, r.status, r.decisionHash);
    }
}

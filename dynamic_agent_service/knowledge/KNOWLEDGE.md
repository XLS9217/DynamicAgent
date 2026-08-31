# Knowledge retrieval

A bucket contains prebuilt blueprint instances. A blueprint describes a kind of
entity and its attributes; each stored knowledge node is one attribute value for
one blueprint instance.

Retrieval searches the knowledge nodes, groups matches by instance, and
reconstructs the corresponding blueprint. Matched attributes contain their
values. Unmatched attributes expose a knowledge-node ID that can be expanded on
demand.

This service only retrieves indexed knowledge. Population and indexing are the
responsibility of the system that owns the source data.

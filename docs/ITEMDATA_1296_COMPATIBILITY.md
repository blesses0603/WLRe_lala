# ItemData 1296 compatibility

The parser recognizes the exact 1296 ItemData_C payload by SHA-256
`5195d5ee8ae201dea55439274914930551176c3fcf50d735e03b09c5d04acbb4`.
It reads two additional bytes at the end of each record and preserves them as
`unknown_tail_1296_hex` (four lowercase hexadecimal digits). The field's meaning
is unknown; no behavior or transaction decision may be inferred from it.

The runtime supplies the exact DataPackage version and rejects unreviewed
versions. Version 1296 also requires the exact payload hash. Earlier reviewed
1262, 1275 and 1286 package identities use the existing parser. Database and offline
entry points that have no version use the exact 1296 hash or otherwise
the legacy layout; neither independently authorizes a runtime.

The private real-data test can be run by setting `WLRE_ITEMDATA_1296_BUNDLE`
to the user's cached official `datapackage_data_i.bundle`. The test verifies the
payload digest, count, full parsing and preservation of every tail byte. It does
not copy or publish official resources. Compatibility is limited to this exact
payload; new versions and changed payloads need review. The meaning of the two
bytes, gameplay behavior, GUI and login have not been validated by this test.

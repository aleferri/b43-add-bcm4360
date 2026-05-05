# A.1 extraction — index

Generated from b43-add-bcm4360/wlDSL-3580_EU.o_save (ELF MIPS BE).
Target function: wlc_phy_rxgainctrl_set_gaintbls_acphy @ 0x4285c (size 0x960).

Files:
  01_rodata_base_tables.txt           — the 10 .rodata blocks referenced by the function
  02_gaintbl_tweaks_symbols.txt       — full content of *_GAINTBL_TWEAKS symbols
                                          (NB: only used by sslpnphy, NOT by this fn)
  03_disasm_annotated.txt             — full objdump output with structural anchors
  04_call_inventory.txt               — 42 call sites with resolved targets + arg analysis
  05_structure_and_router_checklist.md — overview + what to read off the live router

Key deltas vs ROADMAP §2.4:
  - Function complexity: 11 table_writes (not 2), 9 memcpy (not 1), 10 rodata refs (not 4)
  - No ELNA/NINJA/UNO/SMIC selector inside this function — those symbols belong to sslpnphy
  - Real discriminators: chip-id (4360/4352) and phy[218] & 0xc000
  - Table id 0x0b is also written by an out-of-line block at 0x430dc

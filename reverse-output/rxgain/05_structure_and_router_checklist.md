# A.1 — Structural overview & router verification checklist

## Function structure (4 segments, per ROADMAP terminology)

### (a) Preamble + gate (0x4285c .. 0x42a7b, ~95 instructions)
  - Stack frame: 216 bytes; saves ra,s0..s8 to stack
  - Loads 10 base pointers from .rodata (range 0x17758..0x177b0)
    plus 8-bit/16-bit field reads from those bases
  - Stores phy_reg_write fn-ptr at sp+148 (cached for 5 later calls)
  - Initialises constants: s4=0x44 (id1), s5=0x45 (id2), s2=8 (width), s1=0 (loop ctr)

### (b) Body / per-core loop (0x42a8c .. 0x4307b, ~390 instructions)
  - Outer loop on s1, bound = phy[196] (probable num_cores or num_streams)
  - Per iteration:
    * 4 base-table reads from .rodata (block_A or block_B chosen by phy[218]&0xc000)
    * 4 chip-id discriminators (BCM4360 vs BCM4352), each leading to a phy_reg_write
      with a different length immediate (24, 12, 44, 12)
    * 8 wlc_phy_table_read_acphy calls (read into the local stack-resident buffer)
    * memcpy operations to merge the read template + delta
    * 10 wlc_phy_table_write_acphy calls (alternating ids 0x44 / 0x45 with offsets
      0, 8, 16, 32 — the per-core slice of each table)

### (c) Epilogue (0x4307c .. 0x430d8, ~24 instructions)
  - Final 364-byte phy_reg_write call (via cached fn-ptr)
  - Final phy_reg_mod call
  - Restore registers, jr ra

### (d) Out-of-line tail (0x430dc .. 0x431c0, ~50 instructions)
  - 3 memcpy + 1 wlc_phy_table_write_acphy(id=0x0b, len=3, off=11)
  - Targets phy table id 0x0b — distinct from 0x44/0x45
  - Reached via fall-through after the main return; called from somewhere via a
    j (long jump) — appears to be a side-block reused from another control flow,
    OR a tail-call landing from elsewhere. To verify by examining who jumps in.


## What we need from the router (Tier-A → Tier-B handoff)

### Hard requirements before writing C code:

1. **Confirm chip id**:
     `cat /sys/bus/pci/devices/<bcm-bdf>/device` — must be 0x4360 or 0x4352
     OR with the blob driver loaded: dmesg / debug print of acphychipid
     The function discriminates between exactly those two values.

2. **Read phy[218] (halfword) and report (phy[218] & 0xc000)**:
     This drives a top-level branch (block_A vs block_B at 0x42c14).
     If 0 → main path. If non-zero → diverts to the path at 0x42f74.
     Need: the phy_pub_t / phy_info_t field at offset 218 from the blob run-time.
     A simple print after probe is enough: `printk("phy[218]=0x%x", *((u16*)pi+109))`.
     **SALAME** — the interpretation that bits 14–15 of phy[218] are "band/mode
     hi-bits" is an inference, not measured. Empirically all we know is that this
     halfword is read once and masked with 0xc000.

3. **Read phy[196] (byte)**: the loop iteration bound.
     `lbu v0, 196(s0); sltu v0, s1, v0; bne v0, …` — confirmed loop-bound use.
     **SALAME** — the identification with num_cores is a strong prior
     (the AC PHY uses 2069 PHY-reg `0x0B & 0x07` for num_cores, and
     phy[196] would be a sensible cached copy) but is NOT verified by
     finding a writer of phy[196] in the binary. For the 1×1 MVP this is moot,
     but worth confirming when deciding what to force at boot.

4. **Identify the struct pointed to by `pi+168` (size ≥ 1406 bytes)**:
     The function loads s3 in three places:
       - 0x428bc: `lbu s3, 6(t6)` where t6 points into .rodata at 0x177a8 → s3 = 0x09
                  (constant; used as a gate/threshold somewhere in the body)
       - 0x429e8: `lw s3, 168(a0)` → s3 := `*(void**)(pi + 168)` (POINTER reload)
       - 0x430c4: stack restore at epilogue
     After the reload, the function reads `lbu …, 911(s3)`, `lbu …, 1403(s3)`,
     `lbu …, 1404(s3)`, `lbu …, 1405(s3)`. So `pi[168]` is a pointer to a
     sub-structure of at least 1406 bytes. Need: what struct lives at `pi+168`
     in this driver (likely a per-band, per-channel, or per-radio context).
     The contents at offsets 911 and 1403–1405 will be passed as `a2` /
     `a3` arguments to phy_reg_write calls that target the chip-id-discriminated
     paths — i.e. these bytes are board-state inputs to the rxgain compute.

5. **Capture phy table 0x44 and 0x45 contents AFTER blob has run init**:
     Boot the original D-Link blob, let init complete, dump tables 0x44 & 0x45.
     This becomes the GROUND TRUTH the kernel-patch port must replicate.
     Procedure: /sys/kernel/debug/ieee80211/.../b43/.../phytables OR equivalent;
     if not exposed by blob, capture via PCI BAR mmap + register sequence.

### Soft (nice-to-have):

6. Whether the function "tail" at 0x430dc..0x431c0 is reached on this board.
   Strategy: kprobe / breakpoint at 0x430dc-equivalent during the blob's execution.
   If never reached → table id 0x0b is not relevant for this board → skip.

7. Confirmation of the helper-signature ordering:
   wlc_phy_table_write_acphy(pi, id, len, off, src, width)
   The b43 in-tree helper signature differs across PHY families; cross-check with
   how the existing kernel-patch invokes wlc_phy_table_write_acphy in tables_init.


## What is NOT in this extraction (and why)

- No C code. As requested, no function body has been written.
- No board-tweak switch. Cross-ref evidence shows the *_GAINTBL_TWEAKS symbols
  belong to sslpnphy, not acphy. ROADMAP §2.4's claim about an
  ELNA/NINJA/UNO/SMIC selector inside this function is unsupported by the binary.
  The actual discriminators are: (i) chip-id (4360 vs 4352), (ii) phy[218]&0xc000.
- No assumed translation of phy_reg_* offsets to b43 register names. The 4
  phy_reg_write calls inside the function pass register-id immediates that are
  NOT yet mapped to symbolic names; that mapping needs the existing extract_phy_writes
  pre-pass output (acphy_map.txt) to resolve.

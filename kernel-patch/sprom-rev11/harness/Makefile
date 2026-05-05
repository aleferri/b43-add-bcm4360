# Makefile for the bcma_sprom_extract_r11 offline harness.
#
# Build:   make
# Run:     make check       (or ./test)
# Clean:   make clean

CC      ?= gcc
CFLAGS  ?= -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare
LDFLAGS ?=

OBJS = extract_r11.o data_load.o synth_srom.o test.o

test: $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $(OBJS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

extract_r11.o: extract_r11.c kernel_shim.h ssb_sprom.h ssb_regs.h
data_load.o:   data_load.c   data_load.h   kernel_shim.h
synth_srom.o:  synth_srom.c  synth_srom.h  data_load.h ssb_regs.h kernel_shim.h
test.o:        test.c        data_load.h   ssb_sprom.h synth_srom.h

.PHONY: check check-bcm4360usb clean
check: test
	./test

# Second test vector: BCM4360 USB rev-11 reference NVRAM (no raw SROM
# available — runs the synth-based round-trip described in the patch
# series cover letter and in synth_srom.c).
check-bcm4360usb: test
	./test --synth vectors/bcm4360usb.nvram

clean:
	rm -f $(OBJS) test

# Makefile for the bcma_sprom_extract_r11 offline harness.
#
# Build:   make
# Run:     make check       (or ./test)
# Clean:   make clean

CC      ?= gcc
CFLAGS  ?= -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare
LDFLAGS ?=

OBJS = extract_r11.o data_load.o test.o

test: $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $(OBJS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

extract_r11.o: extract_r11.c kernel_shim.h ssb_sprom.h ssb_regs.h
data_load.o:   data_load.c   data_load.h   kernel_shim.h
test.o:        test.c        data_load.h   ssb_sprom.h

.PHONY: check clean
check: test
	./test

clean:
	rm -f $(OBJS) test

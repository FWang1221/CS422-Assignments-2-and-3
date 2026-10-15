CLANG ?= clang
BPFTOOL ?= bpftool
PKG_CONFIG ?= pkg-config
BUILD_DIR ?= $(CURDIR)/build
VMLINUX_BTF ?= /sys/kernel/btf/vmlinux
BPF_CFLAGS := -g -O2 -target bpf -Wall -Werror
LIBBPF_CFLAGS = $(shell $(PKG_CONFIG) --cflags libbpf)
OBJECT := $(BUILD_DIR)/cs422_scaffold.bpf.o

.PHONY: all
all: $(OBJECT)

$(BUILD_DIR):
	mkdir -p "$@"

$(BUILD_DIR)/vmlinux.h: $(VMLINUX_BTF) | $(BUILD_DIR)
	$(BPFTOOL) btf dump file "$(VMLINUX_BTF)" format c > "$@.tmp"
	mv "$@.tmp" "$@"

$(OBJECT): cs422_scaffold.bpf.c $(BUILD_DIR)/vmlinux.h
	$(PKG_CONFIG) --exists libbpf
	$(CLANG) $(BPF_CFLAGS) $(LIBBPF_CFLAGS) -I"$(BUILD_DIR)" -c "$<" -o "$@"

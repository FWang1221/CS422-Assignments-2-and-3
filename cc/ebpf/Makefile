CLANG ?= clang
BPFTOOL ?= bpftool
PKG_CONFIG ?= pkg-config
BUILD_DIR ?= $(CURDIR)/build
VMLINUX_BTF ?= /sys/kernel/btf/vmlinux
BPF_CFLAGS := -g -O2 -target bpf -Wall -Werror
LIBBPF_CFLAGS = $(shell $(PKG_CONFIG) --cflags libbpf)
OBJECTS := $(BUILD_DIR)/cs422_scaffold.bpf.o $(BUILD_DIR)/cs422_handwrite.bpf.o

.PHONY: all test
all: $(OBJECTS)

test: $(BUILD_DIR)/test_controller
	"$(BUILD_DIR)/test_controller"

$(BUILD_DIR):
	mkdir -p "$@"

$(BUILD_DIR)/vmlinux.h: $(VMLINUX_BTF) | $(BUILD_DIR)
	$(BPFTOOL) btf dump file "$(VMLINUX_BTF)" format c > "$@.tmp"
	mv "$@.tmp" "$@"

$(BUILD_DIR)/%.bpf.o: %.bpf.c cs422_controller.h $(BUILD_DIR)/vmlinux.h
	$(PKG_CONFIG) --exists libbpf
	$(CLANG) $(BPF_CFLAGS) $(LIBBPF_CFLAGS) -I"$(BUILD_DIR)" -c "$<" -o "$@"

$(BUILD_DIR)/test_controller: tests/test_controller.c cs422_controller.h | $(BUILD_DIR)
	$(CC) -std=c11 -O2 -Wall -Wextra -Werror -I. "$<" -o "$@"

CLANG ?= clang
BPFTOOL ?= bpftool
LLVM_READELF ?= llvm-readelf
LLVM_OBJDUMP ?= llvm-objdump
PKG_CONFIG ?= pkg-config
BUILD_DIR ?= $(CURDIR)/build
VMLINUX_BTF ?= /sys/kernel/btf/vmlinux
BPF_CFLAGS := -g -O2 -target bpf -Wall -Werror
LIBBPF_CFLAGS = $(shell $(PKG_CONFIG) --cflags libbpf)
OBJECTS := $(BUILD_DIR)/cs422_scaffold.bpf.o $(BUILD_DIR)/cs422_handwrite.bpf.o

.PHONY: all test check-layout check-median-codegen
all: $(OBJECTS)

test: check-layout check-median-codegen $(BUILD_DIR)/test_controller
	"$(BUILD_DIR)/test_controller"

check-layout: $(BUILD_DIR)/cs422_handwrite.bpf.o
	@sections=$$($(LLVM_READELF) --section-headers --wide "$<") || exit 1; \
	for callback in init pkts_acked state ssthresh undo cong_avoid; do \
		printf '%s\n' "$$sections" | grep -Fq " struct_ops/handwrite_$$callback " || { \
			echo "Missing dedicated ELF section for handwrite_$$callback" >&2; exit 1; \
		}; \
	done
	@echo "BPF callback section layout passed"

check-median-codegen: $(BUILD_DIR)/cs422_handwrite.bpf.o
	@code=$$($(LLVM_OBJDUMP) -d --section=struct_ops/handwrite_pkts_acked "$<") || exit 1; \
	masks=$$(printf '%s\n' "$$code" | grep -cE 's>>= (0x3f|63)'); \
	test "$$masks" -eq 36 || { \
		echo "Expected 36 branch-free median compare/exchanges, found $$masks" >&2; exit 1; \
	}
	@echo "BPF branch-free median code generation passed"

$(BUILD_DIR):
	mkdir -p "$@"

$(BUILD_DIR)/vmlinux.h: | $(VMLINUX_BTF) $(BUILD_DIR)
	$(BPFTOOL) btf dump file "$(VMLINUX_BTF)" format c > "$@.tmp"
	mv "$@.tmp" "$@"

$(BUILD_DIR)/%.bpf.o: %.bpf.c cs422_controller.h $(BUILD_DIR)/vmlinux.h
	$(PKG_CONFIG) --exists libbpf
	$(CLANG) $(BPF_CFLAGS) $(LIBBPF_CFLAGS) -I"$(BUILD_DIR)" -c "$<" -o "$@"

$(BUILD_DIR)/test_controller: tests/test_controller.c cs422_controller.h | $(BUILD_DIR)
	$(CC) -std=c11 -O2 -Wall -Wextra -Werror -I. "$<" -o "$@"

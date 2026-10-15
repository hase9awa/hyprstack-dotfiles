CXXFLAGS ?= -O2
CXXFLAGS += -std=c++23 -shared -fPIC -fno-gnu-unique -Wall -Wextra -Wno-unused-parameter -Wno-missing-field-initializers
CPPFLAGS += $(shell pkg-config --cflags hyprland pixman-1 libdrm libinput libudev wayland-server xkbcommon lua)

all: hdr-reference.so

hdr-reference.so: main.cpp capture.hpp client-sdr.hpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $< -o $@

.PHONY: all

/* SPDX-License-Identifier: MIT
 * Adapted from DonFlymoor/FlickrFree, commit 3356907523ade96db948ed99fd9774a73c3b6e77.
 * Copyright (c) 2026 donf. See LICENSE.flickrfree.
 * A transparent, unfocusable 1-pixel surface, paced by Wayland frame callbacks.
 * The Hyprland supervisor removes it on fullscreen and detected output changes.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wayland-client.h>
#include "layer-shell.h"
#include "single-pixel.h"
#include "presentation.h"

struct output {
    struct output *next;
    struct wl_output *resource;
    uint32_t global;
    char *name;
};

struct app {
    struct wl_display *display;
    struct wl_registry *registry;
    struct wl_compositor *compositor;
    struct zwlr_layer_shell_v1 *shell;
    struct wp_single_pixel_buffer_manager_v1 *pixels;
    struct wp_presentation *presentation;
    struct output *outputs, *target;
    const char *output_name;
    struct wl_surface *surface;
    struct zwlr_layer_surface_v1 *layer;
    struct wl_buffer *buffer;
    struct wl_callback *callback;
    bool configured, closed, measure;
    uint64_t callbacks, presented, discarded, last_present, min_interval, max_interval;
    double report_time;
};

static volatile sig_atomic_t stopped;
static void stop(int signum) { (void)signum; stopped = 1; }
static void commit(struct app *a);

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void output_geometry(void *data, struct wl_output *o, int32_t x, int32_t y,
                            int32_t w, int32_t h, int32_t subpixel,
                            const char *make, const char *model, int32_t transform) {
    (void)data; (void)o; (void)x; (void)y; (void)w; (void)h;
    (void)subpixel; (void)make; (void)model; (void)transform;
}
static void output_mode(void *data, struct wl_output *o, uint32_t flags,
                        int32_t w, int32_t h, int32_t rate) {
    (void)data; (void)o; (void)flags; (void)w; (void)h; (void)rate;
}
static void output_done(void *data, struct wl_output *o) { (void)data; (void)o; }
static void output_scale(void *data, struct wl_output *o, int32_t scale) {
    (void)data; (void)o; (void)scale;
}
static void output_name(void *data, struct wl_output *o, const char *name) {
    (void)o;
    struct output *output = data;
    free(output->name);
    output->name = strdup(name);
}
static void output_description(void *data, struct wl_output *o, const char *description) {
    (void)data; (void)o; (void)description;
}
static const struct wl_output_listener output_listener = {
    .geometry = output_geometry, .mode = output_mode, .done = output_done,
    .scale = output_scale, .name = output_name, .description = output_description,
};

static void presentation_clock(void *data, struct wp_presentation *p, uint32_t clock_id) {
    (void)data; (void)p; (void)clock_id;
}
static const struct wp_presentation_listener presentation_listener = {
    .clock_id = presentation_clock,
};
static void feedback_output(void *data, struct wp_presentation_feedback *f, struct wl_output *o) {
    (void)data; (void)f; (void)o;
}
static void feedback_presented(void *data, struct wp_presentation_feedback *f,
                               uint32_t hi, uint32_t lo, uint32_t nsec, uint32_t refresh,
                               uint32_t seq_hi, uint32_t seq_lo, uint32_t flags) {
    (void)refresh; (void)seq_hi; (void)seq_lo; (void)flags;
    struct app *a = data;
    uint64_t time = (((uint64_t)hi << 32) | lo) * UINT64_C(1000000000) + nsec;
    if (a->last_present && time > a->last_present) {
        uint64_t interval = time - a->last_present;
        if (!a->min_interval || interval < a->min_interval) a->min_interval = interval;
        if (interval > a->max_interval) a->max_interval = interval;
    }
    a->last_present = time;
    a->presented++;
    wp_presentation_feedback_destroy(f);
}
static void feedback_discarded(void *data, struct wp_presentation_feedback *f) {
    ((struct app *)data)->discarded++;
    wp_presentation_feedback_destroy(f);
}
static const struct wp_presentation_feedback_listener feedback_listener = {
    .sync_output = feedback_output, .presented = feedback_presented, .discarded = feedback_discarded,
};

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    struct app *a = data;
    if (!strcmp(interface, "wl_compositor") && version >= 4)
        a->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 4);
    else if (!strcmp(interface, "zwlr_layer_shell_v1"))
        a->shell = wl_registry_bind(registry, name, &zwlr_layer_shell_v1_interface, 1);
    else if (!strcmp(interface, "wp_single_pixel_buffer_manager_v1"))
        a->pixels = wl_registry_bind(registry, name, &wp_single_pixel_buffer_manager_v1_interface, 1);
    else if (a->measure && !strcmp(interface, "wp_presentation")) {
        a->presentation = wl_registry_bind(registry, name, &wp_presentation_interface, 1);
        wp_presentation_add_listener(a->presentation, &presentation_listener, a);
    } else if (!strcmp(interface, "wl_output") && version >= 4) {
        struct output *o = calloc(1, sizeof *o);
        if (!o) { a->closed = true; return; }
        o->global = name;
        o->resource = wl_registry_bind(registry, name, &wl_output_interface, 4);
        o->next = a->outputs;
        a->outputs = o;
        wl_output_add_listener(o->resource, &output_listener, o);
    }
}
static void global_removed(void *data, struct wl_registry *registry, uint32_t name) {
    (void)registry;
    struct app *a = data;
    if (a->target && a->target->global == name) a->closed = true;
}
static const struct wl_registry_listener registry_listener = {
    .global = global, .global_remove = global_removed,
};

static void frame_done(void *data, struct wl_callback *callback, uint32_t time) {
    (void)time;
    struct app *a = data;
    wl_callback_destroy(callback);
    a->callback = NULL;
    a->callbacks++;
    if (!stopped && !a->closed) commit(a);
}
static const struct wl_callback_listener frame_listener = { .done = frame_done };
static void commit(struct app *a) {
    if (!a->configured || a->callback) return;
    a->callback = wl_surface_frame(a->surface);
    wl_callback_add_listener(a->callback, &frame_listener, a);
    if (a->presentation) {
        struct wp_presentation_feedback *f = wp_presentation_feedback(a->presentation, a->surface);
        wp_presentation_feedback_add_listener(f, &feedback_listener, a);
    }
    wl_surface_attach(a->surface, a->buffer, 0, 0);
    wl_surface_damage_buffer(a->surface, 0, 0, 1, 1);
    wl_surface_commit(a->surface);
}
static void configure(void *data, struct zwlr_layer_surface_v1 *layer,
                      uint32_t serial, uint32_t w, uint32_t h) {
    (void)w; (void)h;
    struct app *a = data;
    zwlr_layer_surface_v1_ack_configure(layer, serial);
    a->configured = true;
    commit(a);
}
static void closed(void *data, struct zwlr_layer_surface_v1 *layer) {
    (void)layer; ((struct app *)data)->closed = true;
}
static const struct zwlr_layer_surface_v1_listener layer_listener = {
    .configure = configure, .closed = closed,
};

static void report(struct app *a) {
    double time = now(), elapsed = time - a->report_time;
    if (elapsed < 5) return;
    fprintf(stderr, "vrr-pixel[%s]: %.1f frame callbacks/s", a->output_name,
            (double)a->callbacks / elapsed);
    if (a->presentation)
        fprintf(stderr, ", %.1f presentations/s, interval %.2f..%.2f ms, discarded=%" PRIu64,
                (double)a->presented / elapsed, (double)a->min_interval / 1e6,
                (double)a->max_interval / 1e6, a->discarded);
    fputc('\n', stderr);
    a->report_time = time;
    a->callbacks = a->presented = a->discarded = a->min_interval = a->max_interval = 0;
}

static int run(struct app *a) {
    struct pollfd fd = { .fd = wl_display_get_fd(a->display) };
    a->report_time = now();
    while (!stopped && !a->closed) {
        while (wl_display_prepare_read(a->display) != 0)
            if (wl_display_dispatch_pending(a->display) < 0) return 1;
        if (stopped || a->closed) { wl_display_cancel_read(a->display); break; }
        fd.events = POLLIN;
        if (wl_display_flush(a->display) < 0) {
            if (errno != EAGAIN) { wl_display_cancel_read(a->display); return 1; }
            fd.events |= POLLOUT;
        }
        int ready = poll(&fd, 1, 1000);
        if (ready < 0) {
            wl_display_cancel_read(a->display);
            if (errno == EINTR) continue;
            return 1;
        }
        if (fd.revents & POLLIN) {
            if (wl_display_read_events(a->display) < 0) return 1;
        } else wl_display_cancel_read(a->display);
        if (fd.revents & (POLLERR | POLLHUP | POLLNVAL)) return 1;
        if (wl_display_dispatch_pending(a->display) < 0) return 1;
        report(a);
    }
    return 0;
}

int main(int argc, char **argv) {
    if ((argc != 3 && argc != 4) || strcmp(argv[1], "--output") ||
            (argc == 4 && strcmp(argv[3], "--measure"))) {
        fprintf(stderr, "Usage: %s --output DP-1 [--measure]\n", argv[0]);
        return 2;
    }
    struct app a = { .output_name = argv[2], .measure = argc == 4 };
    struct sigaction action = { .sa_handler = stop };
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    a.display = wl_display_connect(NULL);
    if (!a.display) { perror("wl_display_connect"); return 1; }
    a.registry = wl_display_get_registry(a.display);
    wl_registry_add_listener(a.registry, &registry_listener, &a);
    if (wl_display_roundtrip(a.display) < 0 || wl_display_roundtrip(a.display) < 0) return 1;
    for (struct output *o = a.outputs; o; o = o->next)
        if (o->name && !strcmp(o->name, a.output_name)) a.target = o;
    if (!a.target || !a.compositor || !a.shell || !a.pixels || a.closed) {
        fprintf(stderr, "vrr-pixel: output %s or required Wayland protocol unavailable\n", a.output_name);
        return 1;
    }
    a.surface = wl_compositor_create_surface(a.compositor);
    a.layer = zwlr_layer_shell_v1_get_layer_surface(a.shell, a.surface, a.target->resource,
              ZWLR_LAYER_SHELL_V1_LAYER_TOP, "hyprstack-vrr-guard");
    zwlr_layer_surface_v1_add_listener(a.layer, &layer_listener, &a);
    zwlr_layer_surface_v1_set_size(a.layer, 1, 1);
    zwlr_layer_surface_v1_set_anchor(a.layer, ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM |
                                           ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT);
    zwlr_layer_surface_v1_set_exclusive_zone(a.layer, -1);
    zwlr_layer_surface_v1_set_keyboard_interactivity(a.layer,
              ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE);
    struct wl_region *input = wl_compositor_create_region(a.compositor);
    wl_surface_set_input_region(a.surface, input);
    wl_region_destroy(input);
    a.buffer = wp_single_pixel_buffer_manager_v1_create_u32_rgba_buffer(a.pixels, 0, 0, 0, 0);
    wl_surface_commit(a.surface);
    fprintf(stderr, "vrr-pixel[%s]: transparent 1x1, empty input region, keyboard NONE\n", a.output_name);
    int result = run(&a);
    if (a.callback) wl_callback_destroy(a.callback);
    zwlr_layer_surface_v1_destroy(a.layer);
    wl_surface_destroy(a.surface);
    wl_buffer_destroy(a.buffer);
    for (struct output *o = a.outputs; o;) {
        struct output *next = o->next;
        wl_output_release(o->resource);
        free(o->name); free(o); o = next;
    }
    if (a.presentation) wp_presentation_destroy(a.presentation);
    wp_single_pixel_buffer_manager_v1_destroy(a.pixels);
    zwlr_layer_shell_v1_destroy(a.shell);
    wl_compositor_destroy(a.compositor);
    wl_registry_destroy(a.registry);
    wl_display_disconnect(a.display);
    return result;
}

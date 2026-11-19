// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#version 450
layout(set = 0, binding = 0) uniform sampler2D window_image;
layout(push_constant) uniform Crop { ivec2 origin; };
layout(location = 0) out vec4 color;
void main() {
    vec3 rgb = texelFetch(window_image, ivec2(gl_FragCoord.xy) + origin, 0).rgb;
    color = vec4(rgb, 1.0);
}

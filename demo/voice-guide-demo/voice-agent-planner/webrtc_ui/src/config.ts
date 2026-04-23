// SPDX-FileCopyrightText: Copyright (c) 2024-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: BSD 2-Clause License

export const RTC_CONFIG: ConstructorParameters<typeof RTCPeerConnection>[0] = {
  iceServers: [
    {
      urls: [
        "turn:34.142.141.243:3478?transport=udp",
        "turn:34.142.141.243:3478?transport=tcp",
      ],
      username: "turnuser",
      credential: "VLaQxRtCxBR1ixHPBPQyGGTagA7fn0qp",
    },
  ],
};

const host = window.location.hostname;

export const RTC_OFFER_URL = `http://${host}:7860/offer`;

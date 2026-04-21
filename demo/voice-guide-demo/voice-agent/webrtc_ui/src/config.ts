// SPDX-FileCopyrightText: Copyright (c) 2024-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: BSD 2-Clause License

export const RTC_CONFIG: ConstructorParameters<typeof RTCPeerConnection>[0] = {
  iceServers: [
    {
      urls: [
        "turn:<your_turn_host_or_ip>:3478?transport=udp",
        "turn:<your_turn_host_or_ip>:3478?transport=tcp",
      ],
      username: "<your_turn_username>",
      credential: "<your_turn_password>",
    },
  ],
};

const host = window.location.hostname;

export const RTC_OFFER_URL = `http://${host}:7860/offer`;

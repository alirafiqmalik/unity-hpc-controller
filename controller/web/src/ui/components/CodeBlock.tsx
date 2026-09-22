/** A scrolling `<pre>` with a copy button, for a request body or a log tail. */

import styled from '@emotion/styled';
import { IconCheck, IconCopy } from '@tabler/icons-react';
import { useCallback, useEffect, useState } from 'react';

const Wrapper = styled.div<{ $maxHeight: string }>`
  background: ${({ theme }) => theme.background.primary};
  border: 1px solid ${({ theme }) => theme.border.color.light};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  max-height: ${({ $maxHeight }) => $maxHeight};
  overflow: auto;
  position: relative;
`;

const Pre = styled.pre`
  color: ${({ theme }) => theme.font.color.secondary};
  font-size: ${({ theme }) => theme.font.size.xs};
  line-height: 1.65;
  margin: 0;
  padding: ${({ theme }) => theme.spacing(3)};
  white-space: pre-wrap;
  word-break: break-word;
`;

const CopyButton = styled.button`
  align-items: center;
  background: ${({ theme }) => theme.background.tertiary};
  border: 1px solid ${({ theme }) => theme.border.color.medium};
  border-radius: ${({ theme }) => theme.border.radius.sm};
  color: ${({ theme }) => theme.font.color.secondary};
  cursor: pointer;
  display: flex;
  gap: ${({ theme }) => theme.spacing(1)};
  font-size: ${({ theme }) => theme.font.size.xxs};
  padding: ${({ theme }) => theme.spacing(1, 1.5)};
  position: sticky;
  right: ${({ theme }) => theme.spacing(2)};
  top: ${({ theme }) => theme.spacing(2)};
  float: right;
  transition: ${({ theme }) => theme.animation.clickable};
  z-index: 1;

  &:hover {
    color: ${({ theme }) => theme.font.color.primary};
  }
`;

const Caption = styled.div`
  color: ${({ theme }) => theme.accent.primary};
  font-family: ${({ theme }) => theme.font.familyMono};
  font-size: ${({ theme }) => theme.font.size.xs};
  padding: ${({ theme }) => theme.spacing(3, 3, 0)};
`;

export const CodeBlock = ({
  children,
  caption,
  maxHeight = '340px',
}: {
  children: string;
  /** A line above the body, such as the method and path of a request. */
  caption?: string;
  maxHeight?: string;
}) => {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = useCallback(() => {
    const text = caption ? `${caption}\n${children}` : children;
    try {
      void navigator.clipboard?.writeText(text);
      setCopied(true);
    } catch {
      // No clipboard permission. The text stays selectable.
    }
  }, [caption, children]);

  return (
    <Wrapper $maxHeight={maxHeight}>
      <CopyButton type="button" onClick={copy}>
        {copied ? <IconCheck size={11} /> : <IconCopy size={11} />}
        {copied ? 'Copied' : 'Copy'}
      </CopyButton>
      {caption ? <Caption>{caption}</Caption> : null}
      <Pre>{children}</Pre>
    </Wrapper>
  );
};

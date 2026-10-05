import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Button } from '../../ui/components/Button';
import { Card, CardHeader } from '../../ui/components/Card';
import { errorText } from '../controller/api';
import { runnerRequest } from './api';
import { DocumentPreview, type Preview } from './DocumentPreview';
import { ProjectPage } from './ProjectPage';

export const DocumentPage = () => {
  const { slug = '' } = useParams();
  const [value, setValue] = useState<Preview | null>(null);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const load = useCallback(async (offset = 0, version?: string) => {
    const request = ++generation.current;
    try {
      const params = new URLSearchParams({ offset: String(offset), ...(version ? { version } : {}) });
      const result = await runnerRequest<Preview>(slug, `document?${params}`);
      if (request === generation.current) { setValue(result); setError(''); }
    } catch (reason) { if (request === generation.current) setError(errorText(reason)); }
  }, [slug]);
  useEffect(() => { setValue(null); setError(''); void load(); return () => { generation.current += 1; }; }, [load]);
  return <ProjectPage title="Project documentation">
    {error ? <Card role="alert">{error}</Card> : null}
    <Card><CardHeader title={value?.path ?? 'Project documentation'} /><DocumentPreview value={value} />
      {value?.next_offset != null ? <Button onClick={() => void load(value.next_offset!, value.version)}>Next bounded page</Button> : null}
    </Card>
  </ProjectPage>;
};
